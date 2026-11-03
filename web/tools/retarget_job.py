#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一条动作套到目标角色上，输出带动画的 GLB + 预览视频。

用法：
  blender -b -t 4 --factory-startup -P retarget_job.py -- \
      --model 模型.fbx --anim 动作.fbx|.bvh --out 输出目录 --tag 名字 [--frames 24]

状态写到 <out>/status.json，进度打到标准输出（PROGRESS 行）。
"""
import bpy
import json
import math
import os
import subprocess
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


MODEL = arg("--model")
ANIM = arg("--anim")
OUT = arg("--out")
TAG = arg("--tag", "result")
NFRAMES = int(arg("--frames", "24"))
STATUS = os.path.join(OUT, "status.json")


def write_status(state, progress=0, message="", **extra):
    data = {"state": state, "progress": progress, "message": message}
    data.update(extra)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, STATUS)


# ---------------- 骨骼名归一化 ----------------
ALIASES = {
    "hip": "hips", "pelvis": "hips", "root": "hips", "bip01": "hips",
    "abdomen": "spine", "spine": "spine", "spine1": "spine1", "chest": "spine2",
    "upperchest": "spine2", "neck": "neck", "head": "head",
    "lclavicle": "leftshoulder", "lshoulder": "leftarm", "lhupperarm": "leftarm",
    "lhelbow": "leftforearm", "lwrist": "lefthand",
    "rclavicle": "rightshoulder", "rshoulder": "rightarm", "rhupperarm": "rightarm",
    "rhelbow": "rightforearm", "rwrist": "righthand",
    "lupperleg": "leftupleg", "lhipjoint": "leftupleg", "lthigh": "leftupleg",
    "llowerleg": "leftleg", "lknee": "leftleg", "lshin": "leftleg",
    "lfoot": "leftfoot", "ltoes": "lefttoebase", "ltoe": "lefttoebase",
    "rupperleg": "rightupleg", "rhipjoint": "rightupleg", "rthigh": "rightupleg",
    "rlowerleg": "rightleg", "rknee": "rightleg", "rshin": "rightleg",
    "rfoot": "rightfoot", "rtoes": "righttoebase", "rtoe": "righttoebase",
}


def canon(raw):
    n = raw.lower()
    for pre in ("mixamorig:", "mixamorig", "bip01_", "bip01 ", "bip001_", "valvebiped."):
        if n.startswith(pre.lower()):
            n = n[len(pre):]
    n = n.replace("_", "").replace(".", "").replace("-", "").replace(" ", "")
    if n in ALIASES:
        return ALIASES[n]
    if n.startswith("l") and n[1:] in ALIASES:
        return ALIASES[n[1:]]
    if n.startswith("r") and n[1:] in ALIASES:
        return ALIASES[n[1:]]
    return n


def fail(msg):
    write_status("failed", 0, msg)
    print("FAILED", msg)
    sys.exit(0)


os.makedirs(OUT, exist_ok=True)
write_status("running", 2, "打开模型")

if not MODEL or not os.path.isfile(MODEL):
    fail("模型文件不存在")
if not ANIM or not os.path.isfile(ANIM):
    fail("动作文件不存在")

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
ext = os.path.splitext(MODEL)[1].lower()
try:
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=MODEL)
    else:
        bpy.ops.import_scene.fbx(filepath=MODEL)
except Exception as exc:
    fail(f"模型打不开：{exc}")

t_arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if not t_arms:
    fail("这个模型没有骨架。要先在建模软件里蒙皮绑骨，再来套动作。")
t_arm = t_arms[0]
t_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not t_meshes:
    fail("这个模型里没有网格，只有骨架。")

write_status("running", 8, "读取动作")

before = set(bpy.data.objects)
aext = os.path.splitext(ANIM)[1].lower()
try:
    if aext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=ANIM)
    elif aext == ".bvh":
        bpy.ops.import_anim.bvh(filepath=ANIM, global_scale=1.0, use_fps_scale=True)
    else:
        bpy.ops.import_scene.fbx(filepath=ANIM)
except Exception as exc:
    fail(f"动作打不开：{exc}")

src_new = [o for o in bpy.data.objects if o not in before]
s_arms = [o for o in src_new if o.type == "ARMATURE"]
if not s_arms:
    fail("这个文件里没有骨架，不是一条能套的动画。")
s_arm = s_arms[0]
acts = [a for a in bpy.data.actions if a.users > 0] or list(bpy.data.actions)
if not acts:
    fail("动作文件里没有动画数据。")
act = max(acts, key=lambda a: (a.frame_range[1] - a.frame_range[0]))
for o in src_new:
    if o.type == "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
if s_arm.animation_data is None:
    s_arm.animation_data_create()
s_arm.animation_data.action = act
fstart, fend = [int(round(v)) for v in act.frame_range]
if fend <= fstart:
    fail("这条动作没有长度（0 帧）。")

# ---------------- 建立骨骼对应 ----------------
def rest_q(arm, name):
    return (arm.matrix_world @ arm.data.bones[name].matrix_local).to_quaternion()


def rest_p(arm, name):
    return arm.matrix_world @ arm.data.bones[name].matrix_local.translation


tgt_by_canon = {}
for b in t_arm.data.bones:
    tgt_by_canon.setdefault(canon(b.name), b.name)
src_by_canon = {}
for b in s_arm.data.bones:
    src_by_canon.setdefault(canon(b.name), b.name)

pairs = []
for c, tname in tgt_by_canon.items():
    sname = src_by_canon.get(c)
    if sname:
        pairs.append((sname, tname))

write_status("running", 12, f"匹配骨骼 {len(pairs)} 根", matched=len(pairs))
if len(pairs) < 12:
    fail(f"这个动作的骨架和模型对不上（只匹配到 {len(pairs)} 根骨骼），换一条动作试试。")

if "hips" not in [canon(t) for s, t in pairs]:
    fail("动作里找不到根骨（胯骨），没法定位角色。")

t_hip = next(t for s, t in pairs if canon(t) == "hips")
s_hip = next(s for s, t in pairs if canon(t) == "hips")

rt = {t: rest_q(t_arm, t) for s, t in pairs}
rs = {s: rest_q(s_arm, s) for s, t in pairs}
parent_of = {t: (t_arm.data.bones[t].parent.name if t_arm.data.bones[t].parent else None)
             for s, t in pairs}

base_hip_t = rest_p(t_arm, t_hip).z
base_hip_s = rest_p(s_arm, s_hip).z
ratio = (base_hip_t / base_hip_s) if base_hip_s > 0.0001 else 1.0
if not (0.05 < ratio < 20):
    ratio = 1.0
hip_basis = (t_arm.matrix_world @ t_arm.data.bones[t_hip].matrix_local).to_3x3().inverted()

bpy.context.view_layer.objects.active = t_arm
bpy.ops.object.mode_set(mode="POSE")
for b in t_arm.pose.bones:
    b.rotation_mode = "QUATERNION"

name_map = {t: s for s, t in pairs}
total = fend - fstart + 1

for f in range(fstart, fend + 1):
    scn.frame_set(f)
    bpy.context.view_layer.update()
    acc = {}
    for sname, tname in pairs:
        q_src = (s_arm.matrix_world @ s_arm.pose.bones[sname].matrix).to_quaternion().normalized()
        q_des = ((q_src @ rs[sname].inverted()) @ rt[tname]).normalized()
        p = parent_of[tname]
        if p is None or p not in acc:
            base = rt[tname]
        else:
            base = acc[p] @ (rt[p].inverted() @ rt[tname])
        acc[tname] = q_des
        t_arm.pose.bones[tname].rotation_quaternion = (base.inverted() @ q_des).normalized()
        t_arm.pose.bones[tname].keyframe_insert("rotation_quaternion", frame=f)

    sp = s_arm.matrix_world @ s_arm.pose.bones[s_hip].matrix.translation
    want = rest_p(t_arm, t_hip) + (sp - rest_p(s_arm, s_hip)) * ratio
    t_arm.pose.bones[t_hip].location = hip_basis @ (want - rest_p(t_arm, t_hip))
    t_arm.pose.bones[t_hip].keyframe_insert("location", frame=f)

    if f % max(1, total // 10) == 0:
        pct = 15 + int(35 * (f - fstart) / max(1, total))
        print(f"PROGRESS {pct} 套动作 {f - fstart + 1}/{total}", flush=True)
        write_status("running", pct, f"套动作 {f - fstart + 1}/{total}", matched=len(pairs))

bpy.ops.object.mode_set(mode="OBJECT")
scn.frame_start, scn.frame_end = fstart, fend
print("PROGRESS 52 动作套好，准备渲染", flush=True)
write_status("running", 52, "动作套好，准备渲染", matched=len(pairs))

# ---------------- 场景与渲染 ----------------
verts = []
for m in t_meshes:
    mw = m.matrix_world
    for v in list(m.data.vertices)[::8]:
        verts.append(mw @ v.co)
zs = [v.z for v in verts]
xs = [v.x for v in verts]
ys = [v.y for v in verts]
size = max(max(zs) - min(zs), 0.2)
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scn.collection.objects.link(cam)
cam.data.lens = 55
scn.camera = cam

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 4.0
sun.data.angle = math.radians(6)
scn.collection.objects.link(sun)
sun.rotation_euler = (math.radians(58), 0, math.radians(35))

fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", type="AREA"))
fill.data.energy = 150 * size * size
fill.data.size = size * 2
scn.collection.objects.link(fill)
fill.location = (cx - size * 2.5, cy - size * 1.5, size * 1.1)
fill.rotation_euler = (math.radians(75), 0, math.radians(-55))

world = bpy.data.worlds.new("W")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.66, 0.70, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.1
scn.world = world

bpy.ops.mesh.primitive_plane_add(size=size * 14, location=(cx, cy, min(zs)))
ground = bpy.context.active_object
gm = bpy.data.materials.new("Ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.52, 0.54, 0.57, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.92
ground.data.materials.append(gm)

prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = (d.type == "OPTIX")
    scn.cycles.device = "GPU"
except Exception:
    scn.cycles.device = "CPU"

scn.render.engine = "CYCLES"
scn.cycles.samples = 16
scn.cycles.use_denoising = True
scn.render.resolution_x = 360
scn.render.resolution_y = 360
scn.render.image_settings.file_format = "PNG"

frames_dir = os.path.join(OUT, "frames")
os.makedirs(frames_dir, exist_ok=True)
step = max(1, (fend - fstart) // max(1, NFRAMES - 1))
render_frames = list(range(fstart, fend + 1, step))[:NFRAMES]

for i, f in enumerate(render_frames):
    scn.frame_set(f)
    bpy.context.view_layer.update()
    hw = t_arm.matrix_world @ t_arm.pose.bones[t_hip].matrix.translation
    target = Vector((hw.x, hw.y, hw.z - size * 0.02))
    cam.location = target + Vector((size * 1.15, -size * 1.75, size * 0.22))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scn.render.filepath = os.path.join(frames_dir, f"f{i:04d}.png")
    bpy.ops.render.render(write_still=True)
    pct = 55 + int(38 * (i + 1) / len(render_frames))
    print(f"PROGRESS {pct} 渲染 {i + 1}/{len(render_frames)}", flush=True)
    write_status("running", pct, f"渲染 {i + 1}/{len(render_frames)}", matched=len(pairs))

# ---------------- 导出 GLB ----------------
glb = os.path.join(OUT, "result.glb")
bpy.ops.object.select_all(action="DESELECT")
for o in list(t_meshes) + [t_arm]:
    o.select_set(True)
try:
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True,
                              export_animations=True, export_animation_mode="ACTIONS",
                              export_force_sampling=True, export_frame_range=True,
                              export_anim_slide_to_zero=True)
except Exception as exc:
    fail(f"导出 GLB 失败：{exc}")

mp4 = os.path.join(OUT, "preview.mp4")
fps = 18
try:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(frames_dir, "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=360:360", mp4],
                   check=True, timeout=120)
except Exception as exc:
    print("MP4_FAIL", exc, flush=True)

poster = os.path.join(OUT, "poster.jpg")
try:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i",
                    os.path.join(frames_dir, "f0000.png"), "-q:v", "3", poster],
                   check=True, timeout=60)
except Exception:
    pass

write_status("done", 100, "完成", matched=len(pairs), glb=glb, mp4=mp4, poster=poster,
             frames=len(render_frames), duration=round((fend - fstart + 1) / max(scn.render.fps, 1), 2))
print("DONE", flush=True)
