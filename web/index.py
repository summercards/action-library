#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动作库索引脚本 —— 扫描 02_动作数据/ 下的动作文件，写入 library.db。

用法:
    python3 index.py            # 增量重建（保留标签、收藏、缩略图）
    python3 index.py --rebuild  # 清空 assets 重扫（标签关联会重建）
"""
import json
import os
import sqlite3
import struct
import sys
import datetime

ROOT = os.path.expanduser("~/动作库")
DATA_DIR = os.path.join(ROOT, "02_动作数据")
INDEX_DIR = os.path.join(ROOT, "00_说明与索引")
DB_PATH = os.path.join(INDEX_DIR, "library.db")

EXTS = {".bvh", ".glb", ".gltf", ".fbx"}

SOURCE_MAP = {
    "bvh": ("LAFAN1", "研究用途 / Ubisoft La Forge"),
    "gltf": ("Khronos glTF Sample", "CC-BY 4.0"),
    "glb": ("Khronos glTF Sample", "CC-BY 4.0"),
    "fbx": ("待补来源", "待确认"),
}

# 文件名关键词 -> 自动标签
KEYWORD_TAGS = [
    ("walk", "走路"), ("run", "跑步"), ("sprint", "冲刺"),
    ("dance", "舞蹈"), ("fight", "格斗"), ("jump", "跳跃"),
    ("aim", "瞄准"), ("push", "推绊"), ("obstacle", "障碍"),
    ("fall", "摔倒起身"), ("getup", "摔倒起身"), ("ground", "地面"),
    ("carry", "搬运"), ("sword", "器械"), ("idle", "待机"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL,
    source      TEXT,
    license     TEXT,
    format      TEXT,
    path        TEXT,
    rel_path    TEXT UNIQUE,
    duration    REAL DEFAULT 0,
    fps         REAL DEFAULT 0,
    frames      INTEGER DEFAULT 0,
    bones       INTEGER DEFAULT 0,
    nodes       INTEGER DEFAULT 0,
    animations  INTEGER DEFAULT 0,
    size_bytes  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'ok',
    thumb       TEXT,
    favorite    INTEGER DEFAULT 0,
    added       TEXT,
    note        TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT UNIQUE NOT NULL,
    category TEXT DEFAULT '自定义'
);
CREATE TABLE IF NOT EXISTS asset_tags (
    asset_id INTEGER NOT NULL,
    tag_id   INTEGER NOT NULL,
    PRIMARY KEY (asset_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_asset_tags_tag ON asset_tags(tag_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    os.makedirs(INDEX_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def bvh_meta(path):
    """读 BVH 的 HIERARCHY / MOTION 段，返回帧数、帧率、时长、骨骼数。"""
    frames = 0
    frame_time = 0.0
    joints = 0
    in_hierarchy = True
    with open(path, "r", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            up = s.upper()
            if in_hierarchy:
                if up.startswith("JOINT") or up.startswith("ROOT"):
                    joints += 1
                elif up.startswith("MOTION"):
                    in_hierarchy = False
            else:
                if up.startswith("FRAMES:"):
                    try:
                        frames = int(s.split(":", 1)[1].strip())
                    except ValueError:
                        frames = 0
                elif up.startswith("FRAME TIME:"):
                    try:
                        ft = float(s.split(":", 1)[1].strip())
                        frame_time = ft if ft > 0 else 0.0
                    except ValueError:
                        frame_time = 0.0
                    break
    fps = round(1.0 / frame_time, 4) if frame_time > 0 else 0.0
    duration = round(frames * frame_time, 4) if frame_time > 0 else 0.0
    return {"frames": frames, "fps": fps, "duration": duration,
            "bones": joints, "nodes": joints, "animations": 1}


def gltf_json_meta(gltf):
    """从 glTF JSON 结构算动画数、时长、节点数。"""
    accessors = gltf.get("accessors") or []
    animations = gltf.get("animations") or []
    duration = 0.0
    for anim in animations:
        for sampler in anim.get("samplers") or []:
            idx = sampler.get("input")
            if isinstance(idx, int) and 0 <= idx < len(accessors):
                mx = accessors[idx].get("max")
                if isinstance(mx, list) and mx:
                    try:
                        duration = max(duration, float(mx[0]))
                    except (TypeError, ValueError):
                        pass
    return {
        "animations": len(animations),
        "duration": round(duration, 4),
        "nodes": len(gltf.get("nodes") or []),
        "bones": len(gltf.get("skins") or []) and sum(
            len(s.get("joints") or []) for s in gltf.get("skins") or []) or 0,
        "frames": 0,
        "fps": 0.0,
    }


def glb_meta(path):
    """读 GLB 的 JSON chunk（不加载模型本体）。"""
    with open(path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("文件过短")
        magic, version, _length = struct.unpack("<4sII", header)
        if magic != b"glTF":
            raise ValueError("不是 GLB 文件")
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            clen, ctype = struct.unpack("<I4s", head)
            if ctype == b"JSON":
                return gltf_json_meta(json.loads(f.read(clen).decode("utf-8")))
            f.seek(clen, os.SEEK_CUR)
    raise ValueError("未找到 JSON chunk")


def gltf_meta(path):
    with open(path, "r", errors="ignore") as f:
        return gltf_json_meta(json.load(f))


def fbx_meta(path):
    """FBX 目前只记录体积，时长等留待阶段二用 Blender 解析。"""
    return {"frames": 0, "fps": 0.0, "duration": 0.0,
            "bones": 0, "nodes": 0, "animations": 0}


def file_meta(path, ext):
    try:
        if ext == ".bvh":
            return bvh_meta(path)
        if ext == ".glb":
            return glb_meta(path)
        if ext == ".gltf":
            return gltf_meta(path)
    except Exception as exc:  # 解析失败不阻断整库
        print(f"[warn] 解析失败 {path}: {exc}")
        return {"frames": 0, "fps": 0.0, "duration": 0.0,
                "bones": 0, "nodes": 0, "animations": 0}
    return fbx_meta(path)


def scan():
    found = []
    for dirpath, dirnames, filenames in os.walk(DATA_DIR):
        dirnames.sort()
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXTS:
                found.append(os.path.join(dirpath, fn))
    return found


def ensure_tag(con, name, category="自定义"):
    row = con.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute("INSERT INTO tags(name, category) VALUES(?,?)", (name, category))
    return cur.lastrowid


def next_code(con, used):
    n = 1
    while True:
        code = f"A{n:03d}"
        if code not in used and not con.execute(
                "SELECT 1 FROM assets WHERE code=?", (code,)).fetchone():
            return code
        n += 1


def seed_tags(con):
    preset = {
        "动作类": ["走路", "跑步", "冲刺", "跳跃", "舞蹈", "障碍", "摔倒起身",
                   "地面", "瞄准", "推绊", "格斗", "搬运", "待机"],
        "用途": ["预览", "重定向源", "训练集"],
        "风格": ["写实动捕"],
        "来源": ["LAFAN1", "Khronos glTF Sample"],
    }
    for cat, names in preset.items():
        for a in names:
            ensure_tag(con, a, cat)


def main():
    rebuild = "--rebuild" in sys.argv
    con = connect()
    if rebuild:
        con.execute("DELETE FROM asset_tags")
        con.execute("DELETE FROM assets")
        con.commit()
    seed_tags(con)

    files = scan()
    used_codes = {r["code"] for r in con.execute("SELECT code FROM assets")}
    inserted = updated = failed = 0

    for path in files:
        rel = os.path.relpath(path, DATA_DIR)
        ext = os.path.splitext(path)[1].lower()
        sub = rel.split(os.sep)[0].lower()
        fmt = ext.lstrip(".")
        source, license_ = SOURCE_MAP.get(fmt, ("待补来源", "待确认"))
        base_name = os.path.splitext(os.path.basename(path))[0].lower()
        rel_low = rel.replace(os.sep, "/").lower()
        if rel_low.startswith("cmu/"):
            source, license_ = "CMU MoCap", "免费学术使用 / 需确认商用"
        elif base_name.startswith("quat_"):
            source, license_ = "Quaternius", "CC0 1.0"
        elif base_name.startswith("sfu_"):
            source, license_ = "SFU Mocap", "研究用途 / 需确认商用"
        elif base_name.startswith("mixamo_"):
            source, license_ = "Mixamo", "Adobe 免费授权 / 需确认再分发"
        elif base_name.startswith("cmu_"):
            source, license_ = "CMU MoCap", "免费 / 需确认商用"
        elif base_name.startswith("bandai_"):
            source, license_ = "Bandai Namco", "CC BY 4.0"
        if sub == "骨骼模板":
            source, license_ = "自制骨骼模板", "待确认"
        meta = file_meta(path, ext)
        size = os.path.getsize(path)
        name = os.path.splitext(os.path.basename(path))[0]
        row = con.execute("SELECT * FROM assets WHERE rel_path=?", (rel,)).fetchone()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if row:
            con.execute("""UPDATE assets SET name=?, source=?, license=?, format=?,
                path=?, duration=?, fps=?, frames=?, bones=?, nodes=?, animations=?,
                size_bytes=?, status='ok' WHERE id=?""",
                        (name, source, license_, fmt, path, meta["duration"],
                         meta["fps"], meta["frames"], meta["bones"], meta["nodes"],
                         meta["animations"], size, row["id"]))
            asset_id = row["id"]
            updated += 1
        else:
            code = next_code(con, used_codes)
            used_codes.add(code)
            cur = con.execute("""INSERT INTO assets(code, name, source, license, format,
                path, rel_path, duration, fps, frames, bones, nodes, animations,
                size_bytes, status, favorite, added)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ok',0,?)""",
                        (code, name, source, license_, fmt, path, rel, meta["duration"],
                         meta["fps"], meta["frames"], meta["bones"], meta["nodes"],
                         meta["animations"], size, now))
            asset_id = cur.lastrowid
            inserted += 1
            # 自动标签：来源 + 文件名关键词
            con.execute("INSERT OR IGNORE INTO asset_tags(asset_id, tag_id) VALUES(?,?)",
                        (asset_id, ensure_tag(con, source, "来源")))
            low = name.lower()
            for kw, tag in KEYWORD_TAGS:
                if kw in low:
                    con.execute("INSERT OR IGNORE INTO asset_tags(asset_id, tag_id) VALUES(?,?)",
                                (asset_id, ensure_tag(con, tag, "动作类")))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_index',?)", (now,))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('data_dir',?)", (DATA_DIR,))
    con.commit()

    total = con.execute("SELECT COUNT(*) c FROM assets").fetchone()["c"]
    print(f"扫描文件 {len(files)} 个：新增 {inserted}，更新 {updated}，失败 {failed}")
    print(f"数据库：{DB_PATH}，assets 共 {total} 条")
    con.close()


if __name__ == "__main__":
    main()
