---
name: action-library-install
description: 在一台新机器上装好动作库：拉取仓库、安装预览站、把动作文件下载或同步到本地。适合换机器、给同事装、或在第二台电脑上复现同一套动作库。含从零下载和从已有库整包同步两条路。
---

# 动作库：安装与迁移

给新机器装一套能用的动作库。两条路选一条：**从零下载**（干净，但慢）或**从已有库同步**（快，适合内网）。

代码仓库：`https://github.com/summercards/action-library`

---

## 一、先装代码（两条路都要做）

```bash
git clone https://github.com/summercards/action-library.git ~/tools/action-library
```

装技能（让助手能检索到）：

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R ~/tools/action-library/skill/action-library ~/.openclaw/workspace/skills/
```

装依赖，只有三样：

| 依赖 | 用途 | 检查 |
|---|---|---|
| Python 3.8+ | 跑网页服务 | `python3 -V` |
| Blender | 渲缩略图、套动作 | `blender -v` |
| 浏览器 | 看页面 | —— |

没有 Blender 也能用：页面能浏览、能播放，只是没有缩略图、不能套动作。

---

## 二、建目录骨架

```bash
mkdir -p ~/动作库/{00_说明与索引,01_原始下载,02_动作数据,03_整理后,04_临时,05_导出给引擎,90_网页系统}
```

`server.py` 默认读 `~/动作库`。想放别处，加环境变量即可，不用改代码：

```bash
export ACLIB_HOME=/data/动作库
```

---

## 三、把动作弄进来

### 路线 A：从零下载（干净，但耗时间）

按来源逐个下，地址与授权见 `skill/action-library/SKILL.md` 的「素材源总表」。几个上手最快的：

```bash
# Quaternius 动物（CC0，直链可取，214 条带动画 glb）
base=https://quaternius.trebeljahr.com
for p in animals_pack dinosaurs_pack easy_enemies_pack fish_pack; do
  curl -sL -o "01_原始下载/quaternius_${p}.zip" "$base/${p}/download"
done

# Khronos 官方样例（CC-BY，需署名）
curl -sL -o Fox.glb \
  https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Fox/glTF-Binary/Fox.glb

# three.js 动物（MIT，形变动画无骨骼）
for f in Horse Flamingo Stork Parrot; do
  curl -sL -o "${f}.glb" \
    "https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf/${f}.glb"
done

# LAFAN1（研究用途，77 段 BVH，统一骨架）
git clone --depth 1 https://github.com/ubisoft/ubisoft-laforge-animation-dataset ~/tmp/lafan1
```

下完统一解压到 `04_临时/`，核对文件数与时长，再按格式放进 `02_动作数据/{bvh|glb|fbx}/`。

**原始包不要改名、不要删**，它是唯一能回滚的底。

### 路线 B：从已有库整包同步（内网，快）

如果局域网里已有一台装好库的机器，直接同步，省掉几小时下载：

```bash
# 只同步动作数据，不同步原始包（体积减半）
rsync -avz --progress \
  --exclude '01_原始下载' --exclude '04_临时' \
  user@<源主机>:/home/<user>/动作库/02_动作数据/ ~/动作库/02_动作数据/

# 同步索引与规则（很小，但很关键）
rsync -avz user@<源主机>:/home/<user>/动作库/00_说明与索引/ ~/动作库/00_说明与索引/
```

带宽有限就加限速：`--bwlimit=20000`（约 20 MB/s）。

只要某几条动作时，用网页接口按 id 单独取，见下面「单条取用」。

---

## 四、起服务

```bash
cd ~/tools/action-library/web
python3 server.py            # 默认 8099
# 换了库位置：
ACLIB_HOME=/data/动作库 ACLIB_PORT=8100 python3 server.py
```

打开 `http://127.0.0.1:8099`。第一次进来如果列表是空的，说明索引没建：

```bash
curl -X POST http://127.0.0.1:8099/api/reindex
```

---

## 五、验收（别跳过）

```bash
# 1 服务活着
curl -s http://127.0.0.1:8099/api/health
# 期望：{"ok": true, "db": "..."}

# 2 有数据
curl -s "http://127.0.0.1:8099/api/assets?limit=1" | python3 -c "import json,sys;print(json.load(sys.stdin)['total'])"

# 3 随机取一条能下
curl -s -o /tmp/t.glb "http://127.0.0.1:8099/files/1" -w "%{http_code} %{size_download}\n"

# 4 页面能开
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/
```

四条都过，才算装好。只有第 1 条过、第 2 条是 0，就是路径没对上——检查 `ACLIB_HOME`。

---

## 六、单条取用（脚本里用）

```bash
# 按关键词搜，拿 id
curl -s "http://127.0.0.1:8099/api/assets?q=walk&limit=5&offset=0"

# 直接下载文件（dl=1 走 attachment）
curl -OJ "http://127.0.0.1:8099/api/assets/123?dl=1"
# 或者
curl -o walk.glb "http://127.0.0.1:8099/files/123"

# 缩略图
curl -o thumb.png "http://127.0.0.1:8099/thumb/123"
```

`/files/{id}` 支持 Range，视频能拖进度。

---

## 七、许可红线（迁移时别丢）

同步过来的库，`00_说明与索引/授权与署名.md` 一定一起带过去。里面记着每条素材的来源与授权。

| 授权 | 能进商业包 | 要署名 |
|---|---|---|
| CC0 / 公有领域 | 能 | 不用 |
| CC-BY | 能 | 必须 |
| 研究用途 / 仅非商用 | 不能 | —— |
| 授权不明 | 不能 | —— |

**授权记录丢了，整个库就不能商用了**，只能重新一条条查。这一条比装得多快重要。

---

## 八、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面空白 | 浏览器缺 WebGL | 换 Chrome；无头截图加 `--enable-unsafe-swiftshader` |
| 列表 0 条 | 库路径不对 / 没建索引 | 查 `ACLIB_HOME`，再 `POST /api/reindex` |
| 缩略图是粉紫或纯白 | 贴图没跟过来 | 模型与贴图一起打包（zip），别只传单个文件 |
| 端口被占 | 有别的东西在跑 | `ACLIB_PORT=8100` |
| 模型转不动 | 库里是 bvh，页面试图用 glb 播 | 转格式，或换 glb 版本 |
| Blender 报 `slice steps not supported` | Blender 5.2 的限制 | `list(mesh.data.vertices)[::5]`，别用切片步长 |

---

## 九、更新

```bash
cd ~/tools/action-library && git pull
cp -R skill/action-library ~/.openclaw/workspace/skills/     # 技能同步
# 网页服务重启
cd web && ./stop.sh && ./start.sh
```
