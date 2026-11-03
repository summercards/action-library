# 动作库网页系统（端口 8099）

本地浏览、检索、预览动作库的网页工具。数据源是 `~/动作库/02_动作数据/`，索引落在
`~/动作库/00_说明与索引/library.db`（SQLite）。后端只用 Python 3.14 标准库
（`http.server` + `sqlite3`），不依赖 FastAPI/Flask；前端是原生 JS + 本地内置的
Three.js，不走 CDN，断网也能用。

## 快速开始

```bash
cd ~/动作库/90_网页系统
./start.sh                 # 后台启动，默认 8099
open http://127.0.0.1:8099/         # 或在浏览器打开
./stop.sh                  # 停止
```

- 端口可用环境变量改：`ACLIB_PORT=8100 ./start.sh`
- 库根目录默认 `~/动作库`，可用 `ACLIB_HOME` 覆盖
- 进程号写在 `server.pid`，日志在 `logs/server.log`
- 启动脚本会先检查端口占用，起完轮询 `/api/health` 确认真的活了

## 目录

```
90_网页系统/
├── index.html          页面骨架（含内联 favicon，避免 404）
├── static/
│   ├── style.css       三栏布局样式
│   └── app.js          前端逻辑：列表、筛选、标签、3D 视口
├── server.py           HTTP 服务 + API（标准库实现，支持 Range 请求）
├── index.py            扫描 02_动作数据 建索引，写入 library.db
├── vendor/three/       本地 Three.js 0.187.0（含 BVHLoader/GLTFLoader/SkeletonUtils）
├── tools/selfcheck.mjs 无头浏览器端到端自检（需系统 chromium + node）
├── cache/              缩略图与自检截图（可随时删）
├── logs/               运行日志
├── start.sh / stop.sh  启停脚本
└── server.pid          运行中的进程号
```

## 重新建索引

数据目录有增删后：

```bash
python3.14 index.py            # 全量重扫，已存在的按路径更新
curl -s -X POST http://127.0.0.1:8099/api/reindex   # 或走接口触发
```

索引内容：BVH 解析 `HIERARCHY`/`MOTION` 取帧数、帧率、时长、骨骼数；glTF/GLB 读
JSON chunk，从 accessor 的 max 推动画时长。标签按来源与文件名关键词自动打。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活检查 |
| GET | `/api/stats` | 总数、按来源/格式分组统计 |
| GET | `/api/tags` | 全部标签及计数 |
| GET | `/api/assets` | 列表，支持 `q` `source` `tag` `format` `favorite` `limit` `offset` |
| GET | `/api/assets/{id}` | 单条详情 |
| POST | `/api/assets/{id}/tags` | 加标签，body `{"tag":"走路"}` |
| DELETE | `/api/assets/{id}/tags/{tid}` | 删标签 |
| POST | `/api/assets/{id}/favorite` | 收藏/取消，body `{"favorite":true}` |
| POST | `/api/reindex` | 重新扫描数据目录 |
| POST | `/api/upload` | 上传动作文件（multipart，字段名 `file`），成功后返回 `{"ok":true,"asset":{...},"thumb":"/thumb/{id}.png"}` |
| GET | `/files/{id}` | 取原始动作文件，支持 Range（3D 视口按需取字节） |
| GET | `/thumb/{id}.png` | 缩略图（512×512 PNG） |

上传命令示例：

```bash
curl -s -F "file=@/path/to/fox.glb" http://127.0.0.1:8099/api/upload
```

上传流程：先落 `04_临时/上传/` → 校验文件头（GLB 魔数 / BVH 的 HIERARCHY+MOTION / FBX 头）
→ 解析确认动画时长 > 0 → 归位到 `02_动作数据/{格式}/`（重名自动加 `_2`）→ 入库并自动打来源标签
→ 同步渲染缩略图。缩略图失败只把记录标成 `thumb: failed`，不影响文件入库。

## 缩略图

上传时自动渲染一张（动作中间帧，Blender headless，CYCLES CPU，512×512）。批量补历史数据：

```bash
python3.14 make_thumbs.py                      # 补所有缺图，已有图跳过
python3.14 make_thumbs.py --limit 10            # 只补 10 条
python3.14 make_thumbs.py --source LAFAN1       # 只补某个来源
python3.14 make_thumbs.py --force --workers 2   # 全部重渲，并发 2
```

断点续跑：磁盘上已有且大于 2KB 的 PNG 直接跳过；每张先写 `.tmp` 再原子改名，
中途中断不会留半张坏图。每个 Blender 进程限 6 线程，避免把机器打满。

## 3D 预览

- BVH：`BVHLoader` 解析后按第一帧姿势量身高、自动缩放落地；骨骼用线框 + 关节球显示。
  骨骼辅助线和关节球挂在独立的世界坐标层，避免被模型缩放二次缩小。
- 根位移较大的动作（走、跑）镜头会跟随根骨，角色始终留在视口中央。
- glTF/GLB：`GLTFLoader` 加载，播第一条动画。
- 操作：拖拽旋转、滚轮缩放、播放/暂停、循环、倍速、时间轴拖拽。

## 授权与署名

- LAFAN1（Ubisoft La Forge）为**研究用途**，商用需另行取得授权。
- Khronos glTF Sample（Fox、CesiumMan）为 CC-BY 4.0，对外展示需署名。
- 详见 `../00_说明与索引/授权与署名.md`。

## 自检

```bash
node tools/selfcheck.mjs      # 需要 chromium 与 node 在场；输出 JSON，ok:true 即通过
```

覆盖：卡片渲染数量、WebGL 上下文、BVH/glTF 加载与播放推进、标签与收藏落库、
控制台报错、整页截图（存 `cache/_selfcheck.png`）。

## 边界

- 上传会往 `02_动作数据/{格式}/` 写新文件；原始下载包本身不动。
- 不装系统级依赖、不用 sudo、不占 8787/8788 等已用端口。
