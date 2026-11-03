# -*- coding: utf-8 -*-
"""Blender headless 缩略图渲染：动作中间一帧，512x512 PNG。

用法：
  blender -b --factory-startup -P thumb_render.py -- <输入文件> <输出png> [帧位置 0~1]

BVH 只有骨架，没有网格可渲染，这里按目标帧的骨骼姿态现拼一套低模圆柱+关节球，
再打光渲染；glTF/FBX 直接用自带网格。
"""
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SRC, OUT = argv[0], argv[1]
FRAC = float(argv[2]) if len(argv) > 2 else 0.5


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bvh":
        bpy.ops.import_anim.bvh(filepath=path, global_scale=1.0, frame_start=1, use_fps_scale=True)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise RuntimeError("不支持的格式：" + ext)


def all_objects():
    return [o for o in bpy.context.scene.objects]


def set_mid_frame(frac):
    scn = bpy.context.scene
    starts = [o.animation_data.action.frame_range[0] for o in scn.objects
              if o.animation_data and o.animation_data.action]
    ends = [o.animation_data.action.frame_range[1] for o in scn.objects
            if o.animation_data and o.animation_data.action]
    f0 = int(min(starts)) if starts else scn.frame_start
    f1 = int(max(ends)) if ends else scn.frame_end
    frame = int(f0 + (f1 - f0) * max(0.0, min(1.0, frac)))
    scn.frame_set(frame)
    return f0, f1, frame


def mesh_bounds():
    pts = []
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.visible_get():
            for c in o.bound_box:
                pts.append(o.matrix_world @ Vector(c))
    return pts


def build_sticks_from_armature():
    """BVH：按当前帧骨骼姿态拼圆柱与关节球，做成能渲染的低模人形。"""
    arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    if not arm:
        return None
    bpy.context.view_layer.update()
    verts, faces = [], []
    seg = 6

    def add_sphere(center, r):
        base = len(verts)
        rings, segs = 5, 8
        for i in range(rings + 1):
            phi = math.pi * i / rings
            for j in range(segs):
                th = 2 * math.pi * j / segs
                verts.append((center.x + r * math.sin(phi) * math.cos(th),
                              center.y + r * math.sin(phi) * math.sin(th),
                              center.z + r * math.cos(phi)))
        for i in range(rings):
            for j in range(segs):
                a = base + i * segs + j
                b = base + i * segs + (j + 1) % segs
                c = base + (i + 1) * segs + (j + 1) % segs
                d = base + (i + 1) * segs + j
                faces.append((a, b, c, d))

    def add_tube(p0, p1, r):
        axis = p1 - p0
        length = axis.length
        if length < 1e-6:
            return
        base = len(verts)
        n = axis.normalized()
        up = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
        u = n.cross(up).normalized()
        v = n.cross(u).normalized()
        for i in range(seg):
            th = 2 * math.pi * i / seg
            off = u * (r * math.cos(th)) + v * (r * math.sin(th))
            verts.append(tuple(p0 + off))
        for i in range(seg):
            th = 2 * math.pi * i / seg
            off = u * (r * math.cos(th)) + v * (r * math.sin(th))
            verts.append(tuple(p1 + off))
        for i in range(seg):
            a = base + i
            b = base + (i + 1) % seg
            c = base + seg + (i + 1) % seg
            d = base + seg + i
            faces.append((a, b, c, d))

    heads = []
    pairs = []
    mw = arm.matrix_world
    # 必须用姿势后的骨骼端点（pose.bones），静止姿势在 BVH 里常常塌成一条线
    for pb in arm.pose.bones:
        h = mw @ pb.head
        t = mw @ pb.tail
        pairs.append((h, t))
        heads.append(h)
    if not heads:
        return None

    # 按骨架实际尺度决定粗细：厘米级 BVH 用固定半径会细到看不见
    xs = [p.x for p in heads]
    ys = [p.y for p in heads]
    zs = [p.z for p in heads]
    diag = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-4)
    tube_r = diag * 0.013
    joint_r = diag * 0.024

    for h, t in pairs:
        add_tube(h, t, tube_r)
    center = sum(heads, Vector()) / len(heads)
    for h in heads:
        add_sphere(h, joint_r)

    mesh = bpy.data.meshes.new("stick")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    obj = bpy.data.objects.new("stick", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def frame_camera(pts, margin=2.1):
    if not pts:
        pts = [Vector((-1, -1, 0)), Vector((1, 1, 2))]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (mn + mx) / 2
    size = max((mx - mn).x, (mx - mn).y, (mx - mn).z, 0.3)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    # Blender 默认远裁剪 100，BVH 坐标是厘米级，不放开会整个被裁掉
    cam_data.clip_start = max(size * 0.001, 0.01)
    cam_data.clip_end = max(size * 50, 500)
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    dist = size * margin * 0.82
    cam.location = center + Vector((dist * 0.62, -dist * 0.78, size * 0.35))
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return center, size


def setup_lights_world(size, center):
    world = bpy.data.worlds.new("w")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.055, 0.075, 0.11, 1)
        bg.inputs[1].default_value = 1.0

    key = bpy.data.lights.new("key", type="AREA")
    key.energy = 900 * max(size, 0.4) ** 2
    key.size = size * 2.5
    ko = bpy.data.objects.new("key", key)
    ko.location = center + Vector((size * 2, -size * 2.4, size * 2.6))
    ko.rotation_euler = (center - ko.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(ko)

    fill = bpy.data.lights.new("fill", type="AREA")
    fill.energy = 350 * max(size, 0.4) ** 2
    fill.size = size * 3
    fo = bpy.data.objects.new("fill", fill)
    fo.location = center + Vector((-size * 2.2, -size * 1.6, size * 1.2))
    fo.rotation_euler = (center - fo.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(fo)


def add_ground(center, size):
    bpy.ops.mesh.primitive_plane_add(size=size * 12, location=(center.x, center.y, 0))
    plane = bpy.context.object
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.09, 0.11, 0.15, 1)
        bsdf.inputs["Roughness"].default_value = 0.9
    plane.data.materials.append(mat)


def main():
    clear_scene()
    import_any(SRC)
    f0, f1, frame = set_mid_frame(FRAC)

    if not any(o.type == "MESH" for o in bpy.context.scene.objects):
        bpy.context.view_layer.update()
        build_sticks_from_armature()
        bpy.context.view_layer.update()

    pts = mesh_bounds()
    center, size = frame_camera(pts)
    setup_lights_world(size, center)
    # 物体落到地面再加地面，避免悬空
    zmin = min(p.z for p in pts) if pts else 0.0
    add_ground(Vector((center.x, center.y, zmin)), size)

    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 24
    scn.cycles.use_denoising = True
    scn.cycles.max_bounces = 4
    scn.render.resolution_x = 512
    scn.render.resolution_y = 512
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    scn.render.image_settings.file_format = "PNG"
    scn.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print(f"THUMB_OK frame={frame} range={f0}-{f1} size={size:.3f}")


main()
