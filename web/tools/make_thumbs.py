# -*- coding: utf-8 -*-
"""批量补缩略图：遍历库里所有动作，缺图或用旧渲染的重新出一张。

用法：python3 tools/make_thumbs.py [--force] [--limit N]
"""
import os
import sqlite3
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = "/home/sc/动作库/00_说明与索引/library.db"
THUMB_DIR = os.path.join(BASE, "cache", "thumbs")
RENDER = os.path.join(BASE, "tools", "thumb_render.py")
BLENDER = "blender"
THREADS = "6"
TIMEOUT = 300

force = "--force" in sys.argv
limit = None
if "--limit" in sys.argv:
    limit = int(sys.argv[sys.argv.index("--limit") + 1])

os.makedirs(THUMB_DIR, exist_ok=True)
con = sqlite3.connect(DB)
rows = con.execute("SELECT id, path FROM assets ORDER BY id").fetchall()
con.close()

done = skipped = failed = 0
for aid, src in rows:
    out = os.path.join(THUMB_DIR, f"{aid}.png")
    if not force and os.path.isfile(out) and os.path.getsize(out) > 20000:
        skipped += 1
        continue
    if limit is not None and done >= limit:
        break
    if not os.path.isfile(src):
        print(f"[{aid}] 缺源文件 {src}", flush=True)
        failed += 1
        continue
    tmp = os.path.join(THUMB_DIR, f".{aid}.tmp.png")
    try:
        r = subprocess.run(
            [BLENDER, "-b", "-t", THREADS, "--factory-startup", "-P", RENDER, "--", src, tmp, "0.5"],
            capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 20000:
            os.replace(tmp, out)
            done += 1
            print(f"[{aid}] ok {os.path.getsize(out)}", flush=True)
        else:
            failed += 1
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:]
            print(f"[{aid}] fail {tail}", flush=True)
    except subprocess.TimeoutExpired:
        failed += 1
        print(f"[{aid}] timeout", flush=True)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

print(f"DONE made={done} skipped={skipped} failed={failed}", flush=True)
