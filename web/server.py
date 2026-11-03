#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动作库网页系统 —— Python 3.14 标准库 HTTP 服务（端口 8099）。

同一端口同时提供：
  /                      前端静态页
  /api/*                 JSON API
  /files/{id}            动作文件本体（支持 Range）
"""
import email.parser
import email.policy
import json
import mimetypes
import os
import posixpath
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/动作库")
DB_PATH = os.path.join(ROOT, "00_说明与索引", "library.db")
DATA_DIR = os.path.join(ROOT, "02_动作数据")
UPLOAD_TMP = os.path.join(ROOT, "04_临时", "上传")
THUMB_DIR = os.path.join(BASE, "cache", "thumbs")
THUMB_RENDER = os.path.join(BASE, "tools", "thumb_render.py")
BLENDER = "/usr/bin/blender"
THUMB_TIMEOUT = 45
THUMB_THREADS = "6"
MAX_UPLOAD = 300 * 1024 * 1024
HOST = "0.0.0.0"

# ---- 套动作（重定向）----
RIG_ROOT = os.path.join(ROOT, "04_临时", "套动作")
RIG_MODELS = os.path.join(RIG_ROOT, "models")
RIG_JOBS = os.path.join(RIG_ROOT, "jobs")
RIG_TOOL = os.path.join(BASE, "tools", "retarget_job.py")
RIG_INSPECT = os.path.join(BASE, "tools", "inspect_model.py")
MIXAMO_DIR = os.path.join(ROOT, "01_原始下载", "Mixamo", "fbx")
RIG_ANIM_EXT = {".fbx", ".bvh", ".glb", ".gltf"}
RIG_MODEL_EXT = {".fbx", ".glb", ".gltf"}
RIG_MODEL_ALL = RIG_MODEL_EXT | {".zip"}
PORT = int(os.environ.get("ACLIB_PORT", "8099"))

EXT_FORMAT = {".glb": "glb", ".gltf": "gltf", ".fbx": "fbx", ".bvh": "bvh"}
FORMAT_DIR = {"glb": "gltf", "gltf": "gltf", "fbx": "fbx", "bvh": "bvh"}
FORMAT_CN = {"glb": "GLB", "gltf": "glTF", "fbx": "FBX", "bvh": "BVH"}

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("text/plain", ".bvh")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def fmt_size(n):
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} 字节"


def sniff_action_file(filename, data):
    """只靠文件头快速判断。返回 (格式, 报错原因)。报错原因 None 表示通过。"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in EXT_FORMAT:
        return None, "只收 .glb / .gltf / .fbx / .bvh 四种动作文件，这个扩展名不认识。"
    if not data:
        return None, "这个文件是空的（0 字节），检查一下是不是没传完整。"
    fmt = EXT_FORMAT[ext]
    if fmt == "glb":
        if len(data) < 20:
            return None, "这个 .glb 太短了，看着不像二进制模型文件。"
        if data[:4] != b"glTF":
            return None, "这不是真正的 GLB 文件（文件开头不是 glTF 标记）。可能只是把别的文件改成了 .glb 后缀。"
        if data[4:8] != b"\x02\x00\x00\x00":
            return None, "这个 GLB 的版本不是 2，暂时只支持 glTF 2.0。"
    elif fmt == "gltf":
        head = data[:4096].lstrip()
        if not head.startswith(b"{"):
            return None, "这不是真正的 glTF 文件（内容不是 JSON 文本）。"
    elif fmt == "bvh":
        head = data[:65536]
        if b"HIERARCHY" not in head or b"MOTION" not in head:
            return None, "这不是真正的 BVH 动作文件（缺 HIERARCHY 或 MOTION 段）。"
    elif fmt == "fbx":
        head = data[:64]
        if not (head.startswith(b"Kaydara FBX Binary") or b"FBX" in head[:32]):
            return None, "这不是真正的 FBX 文件（缺少 FBX 文件头）。"
    return fmt, None


def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def tags_of(con, asset_ids):
    if not asset_ids:
        return {}
    qs = ",".join("?" * len(asset_ids))
    rows = con.execute(
        f"""SELECT at.asset_id, t.id, t.name, t.category FROM asset_tags at
            JOIN tags t ON t.id = at.tag_id WHERE at.asset_id IN ({qs})
            ORDER BY t.category, t.name""", asset_ids)
    out = {}
    for r in rows:
        out.setdefault(r["asset_id"], []).append(
            {"id": r["id"], "name": r["name"], "category": r["category"]})
    return out


def asset_dict(row, tags):
    d = {k: row[k] for k in row.keys()}
    d["tags"] = tags
    d["favorite"] = bool(d.get("favorite"))
    d["files_url"] = f"/files/{d['id']}"
    return d


def shrink_to_jpg(png_path, jpg_path, size=384, quality=3):
    """把渲染出的 PNG 压成小 JPEG，页面首屏能省一个数量级的流量。"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", png_path,
             "-vf", "scale=%d:%d:force_original_aspect_ratio=decrease" % (size, size),
             "-q:v", str(quality), jpg_path],
            capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and os.path.isfile(jpg_path) and os.path.getsize(jpg_path) > 1000
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ActionLibrary/1.0"

    # ---------- 基础工具 ----------
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _err(self, code, msg):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        q = urllib.parse.parse_qs(parsed.query)
        if path.startswith("/api/"):
            return self.api_get(path, q)
        if path.startswith("/files/"):
            return self.serve_file(path)
        if path.startswith("/thumb/"):
            return self.serve_thumb(path)
        return self.serve_static(path)

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if path == "/api/reindex":
            return self.reindex()
        if path == "/api/upload":
            return self.upload()
        if path == "/api/rig/models":
            return self.rig_upload_model()
        if path == "/api/rig/apply":
            return self.rig_apply()
        m = re.match(r"^/api/assets/(\d+)/tags$", path)
        if m:
            return self.add_tag(int(m.group(1)))
        m = re.match(r"^/api/assets/(\d+)/favorite$", path)
        if m:
            return self.set_favorite(int(m.group(1)))
        return self._err(404, "未知接口")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        m = re.match(r"^/api/assets/(\d+)/tags/(\d+)$", path)
        if m:
            return self.del_tag(int(m.group(1)), int(m.group(2)))
        return self._err(404, "未知接口")

    # ---------- API ----------
    def api_get(self, path, q):
        if path == "/api/health":
            return self._json({"ok": True, "db": DB_PATH})
        if path == "/api/stats":
            return self.stats()
        if path == "/api/tags":
            return self.list_tags()
        if path == "/api/assets":
            return self.list_assets(q)
        m = re.match(r"^/api/assets/(\d+)$", path)
        if m:
            return self.get_asset(int(m.group(1)))
        if path == "/api/rig/models":
            return self.rig_models()
        if path == "/api/rig/animations":
            return self.rig_animations(q)
        if path == "/api/rig/jobs":
            return self.rig_jobs()
        if path == "/api/rig/file":
            return self.rig_file(q)
        return self._err(404, "未知接口")

    def stats(self):
        con = db()
        try:
            total = con.execute("SELECT COUNT(*) c FROM assets").fetchone()["c"]
            sources = [dict(r) for r in con.execute(
                "SELECT source, COUNT(*) c FROM assets GROUP BY source ORDER BY c DESC")]
            formats = [dict(r) for r in con.execute(
                "SELECT format, COUNT(*) c FROM assets GROUP BY format ORDER BY c DESC")]
            fav = con.execute("SELECT COUNT(*) c FROM assets WHERE favorite=1").fetchone()["c"]
            last = con.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
            return self._json({"total": total, "sources": sources, "formats": formats,
                               "favorites": fav,
                               "last_index": last["value"] if last else None})
        finally:
            con.close()

    def list_tags(self):
        con = db()
        try:
            rows = con.execute(
                """SELECT t.id, t.name, t.category, COUNT(at.asset_id) c
                   FROM tags t LEFT JOIN asset_tags at ON at.tag_id = t.id
                   GROUP BY t.id HAVING c > 0
                   ORDER BY t.category, c DESC, t.name""")
            return self._json({"items": [dict(r) for r in rows]})
        finally:
            con.close()

    def list_assets(self, q):
        where, args = [], []
        kw = (q.get("q") or [""])[0].strip()
        if kw:
            where.append("(a.name LIKE ? OR a.code LIKE ? OR a.source LIKE ?)")
            like = f"%{kw}%"
            args += [like, like, like]
        src = (q.get("source") or [""])[0].strip()
        if src:
            where.append("a.source = ?")
            args.append(src)
        tag = (q.get("tag") or [""])[0].strip()
        if tag:
            if tag.isdigit():
                where.append("EXISTS (SELECT 1 FROM asset_tags x WHERE x.asset_id=a.id AND x.tag_id=?)")
                args.append(int(tag))
            else:
                where.append("EXISTS (SELECT 1 FROM asset_tags x JOIN tags t ON t.id=x.tag_id "
                             "WHERE x.asset_id=a.id AND t.name=?)")
                args.append(tag)
        fmt = (q.get("format") or [""])[0].strip()
        if fmt:
            where.append("a.format = ?")
            args.append(fmt)
        if (q.get("favorite") or [""])[0] in ("1", "true"):
            where.append("a.favorite = 1")
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        try:
            limit = min(max(int((q.get("limit") or ["200"])[0]), 1), 1000)
            offset = max(int((q.get("offset") or ["0"])[0]), 0)
        except ValueError:
            limit, offset = 200, 0
        con = db()
        try:
            total = con.execute(f"SELECT COUNT(*) c FROM assets a {sql_where}", args).fetchone()["c"]
            rows = con.execute(
                f"SELECT a.* FROM assets a {sql_where} ORDER BY a.id LIMIT ? OFFSET ?",
                args + [limit, offset]).fetchall()
            tagmap = tags_of(con, [r["id"] for r in rows])
            items = [asset_dict(r, tagmap.get(r["id"], [])) for r in rows]
            return self._json({"total": total, "limit": limit, "offset": offset, "items": items})
        finally:
            con.close()

    def get_asset(self, aid):
        con = db()
        try:
            row = con.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
            if not row:
                return self._err(404, "记录不存在")
            return self._json(asset_dict(row, tags_of(con, [aid]).get(aid, [])))
        finally:
            con.close()

    def add_tag(self, aid):
        body = self._body()
        name = (body.get("name") or body.get("tag") or "").strip()
        tid = body.get("tagId")
        cat = (body.get("category") or "自定义").strip() or "自定义"
        con = db()
        try:
            if not con.execute("SELECT 1 FROM assets WHERE id=?", (aid,)).fetchone():
                return self._err(404, "记录不存在")
            if tid:
                row = con.execute("SELECT id FROM tags WHERE id=?", (int(tid),)).fetchone()
                if not row:
                    return self._err(404, "标签不存在")
                tid = row["id"]
            elif name:
                row = con.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
                tid = row["id"] if row else con.execute(
                    "INSERT INTO tags(name, category) VALUES(?,?)", (name, cat)).lastrowid
            else:
                return self._err(400, "需要 name 或 tagId")
            con.execute("INSERT OR IGNORE INTO asset_tags(asset_id, tag_id) VALUES(?,?)", (aid, tid))
            con.commit()
            return self._json({"ok": True, "tags": tags_of(con, [aid]).get(aid, [])})
        finally:
            con.close()

    def del_tag(self, aid, tid):
        con = db()
        try:
            con.execute("DELETE FROM asset_tags WHERE asset_id=? AND tag_id=?", (aid, tid))
            con.commit()
            return self._json({"ok": True, "tags": tags_of(con, [aid]).get(aid, [])})
        finally:
            con.close()

    def set_favorite(self, aid):
        body = self._body()
        fav = 1 if body.get("favorite") else 0
        con = db()
        try:
            if not con.execute("SELECT 1 FROM assets WHERE id=?", (aid,)).fetchone():
                return self._err(404, "记录不存在")
            con.execute("UPDATE assets SET favorite=? WHERE id=?", (fav, aid))
            con.commit()
            return self._json({"ok": True, "favorite": bool(fav)})
        finally:
            con.close()

    # ---------- 套动作（重定向）----------
    def _rig_model_list(self):
        out = []
        if not os.path.isdir(RIG_MODELS):
            return out
        for fn in sorted(os.listdir(RIG_MODELS)):
            full = os.path.join(RIG_MODELS, fn)
            if os.path.isdir(full):
                # zip 解出来的模型：目录里有 _model.json 和一个模型文件
                meta = self._rig_read_json(os.path.join(full, "_model.json"))
                mf = None
                for cand in sorted(os.listdir(full)):
                    cp = os.path.join(full, cand)
                    if os.path.isfile(cp) and os.path.splitext(cand)[1].lower() in RIG_MODEL_EXT:
                        mf = cp
                        break
                if not mf:
                    continue
                n_tex = 0
                for root, _d, files in os.walk(full):
                    for f2 in files:
                        if os.path.splitext(f2)[1].lower() in {".png", ".jpg", ".jpeg", ".tga", ".bmp"}:
                            n_tex += 1
                out.append({"id": os.path.relpath(mf, RIG_MODELS),
                            "name": meta.get("nice_name") or os.path.splitext(os.path.basename(mf))[0],
                            "size": os.path.getsize(mf), "bones": meta.get("bones"),
                            "meshes": meta.get("meshes"), "verts": meta.get("verts"),
                            "rigged": meta.get("rigged"), "textures": n_tex,
                            "uploaded": int(os.path.getmtime(mf))})
                continue
            if os.path.splitext(fn)[1].lower() not in RIG_MODEL_EXT:
                continue
            meta = self._rig_read_json(full + ".json")
            out.append({"id": fn, "name": meta.get("nice_name") or os.path.splitext(fn)[0],
                        "size": os.path.getsize(full), "bones": meta.get("bones"),
                        "meshes": meta.get("meshes"), "verts": meta.get("verts"),
                        "rigged": meta.get("rigged"), "textures": meta.get("textures"),
                        "uploaded": int(os.path.getmtime(full))})
        out.sort(key=lambda x: -x["uploaded"])
        return out

    def rig_models(self):
        return self._json({"items": self._rig_model_list()})

    def rig_animations(self, q):
        kw = (q.get("q") or [""])[0].strip().lower()
        items = []
        if os.path.isdir(MIXAMO_DIR):
            for fn in sorted(os.listdir(MIXAMO_DIR)):
                stem, ext = os.path.splitext(fn)
                if ext.lower() not in RIG_ANIM_EXT:
                    continue
                if kw and kw not in stem.lower():
                    continue
                items.append({"id": f"m:{fn}", "name": stem.replace("_", " "),
                              "source": "Mixamo", "format": ext.lstrip(".").lower()})
        con = db()
        try:
            rows = con.execute(
                "SELECT id,name,format,source,duration FROM assets "
                "WHERE format IN ('bvh','fbx','glb','gltf') ORDER BY id").fetchall()
        finally:
            con.close()
        for r in rows:
            nm = (r["name"] or "").lower()
            if kw and kw not in nm and kw not in (r["source"] or "").lower():
                continue
            items.append({"id": f"a:{r['id']}", "name": r["name"], "source": r["source"],
                          "format": r["format"], "duration": r["duration"]})
        total = len(items)
        return self._json({"total": total, "items": items[:200]})

    def _rig_resolve_anim(self, aid):
        if not aid:
            return None, None, "没有选动作"
        if aid.startswith("m:"):
            fn = os.path.basename(aid[2:])
            fp = os.path.join(MIXAMO_DIR, fn)
            if not os.path.isfile(fp):
                return None, None, "这个 Mixamo 动作文件不见了"
            return fp, os.path.splitext(fn)[0].replace("_", " "), None
        if aid.startswith("a:"):
            try:
                n = int(aid[2:])
            except ValueError:
                return None, None, "动作编号不对"
            con = db()
            try:
                row = con.execute("SELECT path,name FROM assets WHERE id=?", (n,)).fetchone()
            finally:
                con.close()
            if not row or not os.path.isfile(row["path"]):
                return None, None, "这个动作的文件找不到了"
            return row["path"], row["name"], None
        return None, None, "动作编号格式不认识"

    def rig_upload_model(self):
        os.makedirs(RIG_MODELS, exist_ok=True)
        filename, data = self._multipart_file()
        if not filename:
            return self._err(400, "没收到模型文件，用网页上的「选择模型」按钮再试一次。")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in RIG_MODEL_ALL:
            return self._err(400, "模型只收 .fbx / .glb / .gltf，或者打包成 .zip 一起传（贴图放进去就不会变白）。")
        if not data:
            return self._err(400, "这个文件是空的，检查一下是不是没传完。")
        if ext == ".zip" and data[:2] != b"PK":
            return self._err(400, "这不是真正的 zip 压缩包。")
        if ext == ".glb" and data[:4] != b"glTF":
            return self._err(400, "这不是真正的 GLB 文件（文件头不对）。")
        if ext == ".fbx" and not (data[:20].startswith(b"Kaydara FBX Binary") or b"FBX" in data[:32]):
            return self._err(400, "这不是真正的 FBX 文件。")

        stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", os.path.splitext(filename)[0]).strip() or "model"
        stem = re.sub(r"[^\w\-]+", "_", stem)[:40].strip("_") or "model"

        if ext == ".zip":
            return self._rig_upload_zip(filename, stem, data)

        dest = os.path.join(RIG_MODELS, f"{int(time.time())}_{stem}{ext}")
        try:
            with open(dest, "wb") as f:
                f.write(data)
        except OSError as exc:
            return self._err(500, f"存文件失败：{exc}")

        # 同名贴图目录（如 xxx.fbm）如果已经在服务器上，Blender 导入时会自动找到
        info = {"bones": None, "meshes": None, "verts": None, "rigged": None,
                "nice_name": os.path.splitext(filename)[0]}
        if os.path.isfile(BLENDER) and os.path.isfile(RIG_INSPECT):
            try:
                r = subprocess.run([BLENDER, "-b", "-t", "2", "--factory-startup",
                                    "-P", RIG_INSPECT, "--", dest],
                                   capture_output=True, text=True, timeout=120)
                for line in r.stdout.splitlines():
                    if line.startswith("INSPECT "):
                        info.update(json.loads(line[8:]))
            except Exception as exc:
                info["note"] = f"结构检查没跑成（{exc}），不影响套动作。"
        if info.get("rigged") is False:
            try:
                os.remove(dest)
            except OSError:
                pass
            return self._err(400, "这个模型里面没有骨架。得先在建模软件里蒙皮绑骨，再来套动作。")
        try:
            with open(dest + ".json", "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
        except OSError:
            pass
        return self._json({"ok": True, "model": {
            "id": os.path.basename(dest), "name": info["nice_name"],
            "size": len(data), "bones": info.get("bones"),
            "meshes": info.get("meshes"), "verts": info.get("verts"),
            "rigged": info.get("rigged")}})

    def _rig_upload_zip(self, filename, stem, data):
        """收 zip：里面可以有模型 + 贴图 + .fbm 目录，解到独立文件夹里，贴图自动跟上。"""
        import io
        import zipfile

        folder = os.path.join(RIG_MODELS, f"{int(time.time())}_{stem}")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return self._err(500, f"建目录失败：{exc}")
        model_path = None
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                total = 0
                for zi in zf.infolist():
                    name = zi.filename
                    if name.endswith("/"):
                        continue
                    # 防目录穿越
                    norm = os.path.normpath(name).replace("\\", "/")
                    if norm.startswith("../") or "/../" in norm or norm.startswith("/"):
                        continue
                    total += zi.file_size
                    if total > MAX_UPLOAD:
                        return self._err(400, "压缩包解开后太大了，超过 300 MB。")
                    target = os.path.join(folder, norm)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(zi) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    if os.path.splitext(norm)[1].lower() in RIG_MODEL_EXT:
                        if model_path is None or os.path.getsize(target) > os.path.getsize(model_path):
                            model_path = target
        except zipfile.BadZipFile:
            return self._err(400, "压缩包坏了，重新压一次再传。")
        except OSError as exc:
            return self._err(500, f"解压失败：{exc}")

        if not model_path:
            return self._err(400, "压缩包里没找到 .fbx / .glb / .gltf 模型文件。")

        info = {"bones": None, "meshes": None, "verts": None, "rigged": None,
                "nice_name": os.path.splitext(os.path.basename(model_path))[0]}
        if os.path.isfile(BLENDER) and os.path.isfile(RIG_INSPECT):
            try:
                r = subprocess.run([BLENDER, "-b", "-t", "2", "--factory-startup",
                                    "-P", RIG_INSPECT, "--", model_path],
                                   capture_output=True, text=True, timeout=120)
                for line in r.stdout.splitlines():
                    if line.startswith("INSPECT "):
                        info.update(json.loads(line[8:]))
            except Exception as exc:
                info["note"] = f"结构检查没跑成（{exc}），不影响套动作。"
        if info.get("rigged") is False:
            return self._err(400, "这个模型里面没有骨架。得先在建模软件里蒙皮绑骨，再来套动作。")

        rel = os.path.relpath(model_path, RIG_MODELS)
        try:
            with open(os.path.join(folder, "_model.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
        except OSError:
            pass
        n_tex = 0
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                if os.path.splitext(fn)[1].lower() in {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}:
                    n_tex += 1
        return self._json({"ok": True, "model": {
            "id": rel, "name": info["nice_name"],
            "size": len(data), "bones": info.get("bones"),
            "meshes": info.get("meshes"), "verts": info.get("verts"),
            "rigged": info.get("rigged"), "textures": n_tex}})

    def rig_apply(self):
        body = self._body()
        mid = (body.get("model") or "").strip()
        anim_id = (body.get("anim") or "").strip()
        if not mid or ".." in mid or mid.startswith("/"):
            return self._err(400, "先选一个模型")
        mpath = os.path.normpath(os.path.join(RIG_MODELS, mid))
        if not mpath.startswith(RIG_MODELS) or not os.path.isfile(mpath):
            return self._err(404, "这个模型不在服务器上，重新上传一次。")
        apath, aname, err = self._rig_resolve_anim(anim_id)
        if err:
            return self._err(400, err)
        if not os.path.isfile(BLENDER):
            return self._err(500, "这台机器没装 Blender，套不了动作。")

        os.makedirs(RIG_JOBS, exist_ok=True)
        jid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
        jdir = os.path.join(RIG_JOBS, jid)
        os.makedirs(jdir, exist_ok=True)
        meta = {"id": jid, "model": mid, "model_name": os.path.splitext(mid)[0],
                "anim": anim_id, "anim_name": aname, "created": int(time.time())}
        with open(os.path.join(jdir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        with open(os.path.join(jdir, "status.json"), "w", encoding="utf-8") as f:
            json.dump({"state": "running", "progress": 1, "message": "排队中"}, f, ensure_ascii=False)

        try:
            with open(os.path.join(jdir, "blender.log"), "wb") as log:
                proc = subprocess.Popen(
                    [BLENDER, "-b", "-t", "4", "--factory-startup", "-P", RIG_TOOL, "--",
                     "--model", mpath, "--anim", apath, "--out", jdir, "--tag", jid,
                     "--frames", "24"],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except Exception as exc:
            return self._err(500, f"启动套动作失败：{exc}")
        meta["pid"] = proc.pid
        with open(os.path.join(jdir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        return self._json({"ok": True, "job": meta})

    def _rig_read_json(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def rig_jobs(self):
        items = []
        if os.path.isdir(RIG_JOBS):
            for jid in sorted(os.listdir(RIG_JOBS), reverse=True)[:30]:
                jdir = os.path.join(RIG_JOBS, jid)
                if not os.path.isdir(jdir):
                    continue
                meta = self._rig_read_json(os.path.join(jdir, "meta.json"))
                st = self._rig_read_json(os.path.join(jdir, "status.json"))
                pid = meta.get("pid")
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except OSError:
                        alive = False
                if not alive and st.get("state") == "running":
                    if os.path.isfile(os.path.join(jdir, "result.glb")):
                        st["state"] = "done"
                        st["progress"] = 100
                    else:
                        st["state"] = "failed"
                        st["message"] = "这个任务中断了（可能机器重启或服务停过），重新套一次。"
                item = dict(meta)
                for k in ("state", "progress", "message", "matched", "frames"):
                    item[k] = st.get(k)
                item["has_video"] = os.path.isfile(os.path.join(jdir, "preview.mp4"))
                item["has_glb"] = os.path.isfile(os.path.join(jdir, "result.glb"))
                items.append(item)
        return self._json({"items": items})

    def rig_file(self, q):
        jid = (q.get("id") or [""])[0]
        what = (q.get("what") or ["glb"])[0]
        if not jid or "/" in jid or ".." in jid:
            return self._err(404, "任务不存在")
        names = {"glb": ("result.glb", "model/gltf-binary", "anim.glb"),
                 "mp4": ("preview.mp4", "video/mp4", "preview.mp4"),
                 "poster": ("poster.jpg", "image/jpeg", "poster.jpg")}
        if what not in names:
            return self._err(404, "没有这种产出")
        fn, ctype, dl = names[what]
        fp = os.path.join(RIG_JOBS, jid, fn)
        if not os.path.isfile(fp):
            return self._err(404, "产物还没生成")
        with open(fp, "rb") as f:
            data = f.read()
        extra = {"Cache-Control": "no-store"}
        if q.get("dl"):
            extra["Content-Disposition"] = f'attachment; filename="{jid}_{dl}"'
        return self._send(200, data, ctype, extra=extra)

    def reindex(self):
        try:
            out = subprocess.run([sys.executable, os.path.join(BASE, "index.py")],
                                 capture_output=True, text=True, timeout=300)
            return self._json({"ok": out.returncode == 0,
                               "stdout": out.stdout[-2000:], "stderr": out.stderr[-2000:]})
        except Exception as exc:
            return self._err(500, f"索引失败: {exc}")

    # ---------- 上传与缩略图 ----------
    def _multipart_file(self):
        """返回 (filename, bytes)；不是 multipart 或没有文件则返回 (None, None)。"""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype.lower():
            return None, None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, None
        if n <= 0:
            return None, None
        if n > MAX_UPLOAD:
            return None, None
        raw = self.rfile.read(n)
        msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            b"Content-Type: " + ctype.encode("utf-8", "replace") +
            b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        for part in msg.iter_parts():
            fn = part.get_filename()
            if fn:
                return os.path.basename(fn), part.get_payload(decode=True) or b""
        return None, None

    def upload(self):
        ctype = self.headers.get("Content-Type", "")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_UPLOAD:
            return self._err(413, f"文件太大（上限 {fmt_size(MAX_UPLOAD)}），请先压缩或分段处理。")
        filename, data = self._multipart_file()
        if not filename:
            hint = "请求不是文件上传格式" if "multipart/form-data" not in ctype.lower() else "没找到文件内容"
            return self._err(400, f"上传没成功：{hint}。用网页上的「⬆ 上传」按钮，或把文件拖进页面。")
        fmt, reason = sniff_action_file(filename, data)
        if reason:
            return self._err(400, reason)

        os.makedirs(UPLOAD_TMP, exist_ok=True)
        stem, ext = os.path.splitext(filename)
        safe_stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem).strip() or "upload"
        tmp_path = os.path.join(UPLOAD_TMP, f"{int(time.time())}_{uuid.uuid4().hex[:6]}_{safe_stem}{ext.lower()}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
        except OSError as exc:
            return self._err(500, f"服务器写临时文件失败：{exc}")

        # 解析校验：能不能读出动画；读出时长必须 > 0（FBX 暂不深入解析）
        try:
            sys.path.insert(0, BASE)
            import index as index_mod
            meta = index_mod.file_meta(tmp_path, ext.lower())
        except Exception as exc:
            os.remove(tmp_path)
            return self._err(400, f"这个文件解析不了（{exc}），可能已经损坏。")
        if fmt in ("glb", "gltf", "bvh") and not (meta.get("duration") or 0) > 0:
            os.remove(tmp_path)
            return self._err(400, "文件能打开，但里面没有可用的动画（时长是 0）。换一个有动作的版本再传。")

        dest_dir = os.path.join(DATA_DIR, FORMAT_DIR[fmt])
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{safe_stem}{ext.lower()}")
        n2 = 2
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{safe_stem}_{n2}{ext.lower()}")
            n2 += 1
        try:
            shutil.move(tmp_path, dest)
        except OSError as exc:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return self._err(500, f"归位文件失败：{exc}")

        # 入库（复用 index.py，保持字段与自动标签一致）
        rel = os.path.relpath(dest, DATA_DIR)
        try:
            subprocess.run([sys.executable, os.path.join(BASE, "index.py")],
                           capture_output=True, text=True, timeout=180)
        except Exception as exc:
            return self._err(500, f"文件已存好，但入库失败：{exc}")
        con = db()
        try:
            row = con.execute("SELECT * FROM assets WHERE rel_path=?", (rel,)).fetchone()
        finally:
            con.close()
        if not row:
            return self._err(500, "文件已存好，但索引里找不到这条记录，点「↻ 重新索引」再试。")

        aid = row["id"]
        thumb_url, thumb_note = self.make_thumb(aid, dest)
        con = db()
        try:
            row = con.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
            asset = asset_dict(row, tags_of(con, [aid]).get(aid, []))
        finally:
            con.close()
        return self._json({"ok": True, "asset": asset, "thumb": thumb_url or "failed",
                           "notice": thumb_note})

    def make_thumb(self, aid, src):
        """同步渲染一张缩略图；失败只标记，不影响上传事务。"""
        os.makedirs(THUMB_DIR, exist_ok=True)
        out = os.path.join(THUMB_DIR, f"{aid}.png")
        tmp = os.path.join(THUMB_DIR, f".{aid}.tmp.png")
        note = ""
        ok = False
        try:
            if not os.path.isfile(BLENDER):
                note = "这台机器没装 Blender，缩略图跳过了。"
            else:
                r = subprocess.run(
                    [BLENDER, "-b", "-t", THUMB_THREADS, "--factory-startup", "-P", THUMB_RENDER, "--", src, tmp, "0.5"],
                    capture_output=True, text=True, timeout=THUMB_TIMEOUT)
                if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 2000:
                    jpg = os.path.join(THUMB_DIR, f"{aid}.jpg")
                    if shrink_to_jpg(tmp, jpg):
                        if os.path.exists(out):
                            try:
                                os.remove(out)
                            except OSError:
                                pass
                        ok = True
                    else:
                        os.replace(tmp, out)
                        ok = True
                else:
                    note = "文件已入库，缩略图没渲染出来（可以稍后跑 make_thumbs.py 补）。"
        except subprocess.TimeoutExpired:
            note = f"缩略图渲染超过 {THUMB_TIMEOUT} 秒，先跳过了，稍后可补。"
        except Exception as exc:
            note = f"缩略图渲染出错（{exc}），不影响文件入库。"
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        con = db()
        try:
            con.execute("UPDATE assets SET thumb=? WHERE id=?",
                        (f"/thumb/{aid}.png" if ok else "failed", aid))
            con.commit()
        finally:
            con.close()
        return (f"/thumb/{aid}.png" if ok else None), note

    def serve_thumb(self, path):
        m = re.match(r"^/thumb/(\d+)\.(?:png|jpg)$", path)
        if not m:
            return self._err(404, "缩略图不存在")
        aid = m.group(1)
        jpg = os.path.join(THUMB_DIR, f"{aid}.jpg")
        png = os.path.join(THUMB_DIR, f"{aid}.png")
        if os.path.isfile(jpg):
            fp, ctype = jpg, "image/jpeg"
        else:
            fp, ctype = png, "image/png"
        if not os.path.isfile(fp):
            return self._err(404, "缩略图不存在")
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, extra={"Cache-Control": "public, max-age=86400"})

    # ---------- 文件 ----------
    def serve_file(self, path):
        m = re.match(r"^/files/(\d+)$", path)
        if not m:
            return self._err(404, "路径错误")
        con = db()
        try:
            row = con.execute("SELECT path, name, format FROM assets WHERE id=?", (int(m.group(1)),)).fetchone()
        finally:
            con.close()
        if not row:
            return self._err(404, "记录不存在")
        fp = row["path"]
        if not os.path.isfile(fp):
            return self._err(404, "文件已不存在")
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if row["format"] == "bvh":
            ctype = "text/plain; charset=utf-8"
        size = os.path.getsize(fp)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng:
            mm = re.match(r"bytes=(\d*)-(\d*)", rng)
            if mm:
                partial = True
                if mm.group(1):
                    start = int(mm.group(1))
                    end = int(mm.group(2)) if mm.group(2) else size - 1
                else:
                    start = max(size - int(mm.group(2) or 0), 0)
                end = min(end, size - 1)
                if start > end:
                    return self._send(416, b"", extra={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(fp, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except BrokenPipeError:
                    return
                left -= len(chunk)

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        safe = posixpath.normpath(path).lstrip("/")
        fp = os.path.join(BASE, safe)
        if not os.path.abspath(fp).startswith(BASE + os.sep) or not os.path.isfile(fp):
            return self._err(404, "文件不存在")
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, data, ctype)


def main():
    if not os.path.isfile(DB_PATH):
        print(f"[!] 数据库不存在：{DB_PATH}，先运行 index.py")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"动作库服务启动： http://{HOST}:{PORT}  (db={DB_PATH})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
