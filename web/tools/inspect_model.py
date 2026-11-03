#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查一个模型文件有没有骨架、多少网格顶点。输出一行 INSPECT {json}。"""
import bpy
import json
import os
import sys

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
path = argv[0] if argv else ""
info = {"bones": 0, "meshes": 0, "verts": 0, "rigged": False, "names": []}

if path and os.path.isfile(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        else:
            bpy.ops.import_scene.fbx(filepath=path)
    except Exception as exc:
        info["error"] = str(exc)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    info["meshes"] = len(meshes)
    info["verts"] = sum(len(m.data.vertices) for m in meshes)
    if arms:
        info["bones"] = len(arms[0].data.bones)
        info["rigged"] = True
        info["names"] = [b.name for b in list(arms[0].data.bones)[:8]]
    info["skinned"] = any(m.vertex_groups for m in meshes)

print("INSPECT " + json.dumps(info, ensure_ascii=False))
