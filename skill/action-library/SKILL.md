---
name: action-library
description: 建立并维护一个本地 3D 动作素材库（mocap / 动画包 / 带动画角色），含来源搜集、许可判定、批量下载、六层目录入库、多维标签分类、缩略图渲染、网页浏览与「给模型套动作」重定向工具。用于扩充动作库、把新下载的动画包整理入库、或从零搭一套可长期用的动作素材站。
---

# 动作库：搜集 + 建库 + 预览站

一套从「网上找动作」到「网页上看、能套到自己角色上」的完整流程。核心是三件事：**找得准、许可干净、能长期用**。

## 什么时候用这个技能

- 要给项目补动作素材（人形 / 非人形 / 怪兽 / 虫类）
- 手上有一堆下载的动画包，需要解开、转格式、分类、生成缩略图
- 要搭或修一个本地动作预览站
- 要把自己角色的模型套上库里的动作，导出带动画的 GLB

## 安装与获取

仓库地址：`https://github.com/summercards/action-library`

### 方式一：只取技能

```bash
git clone --depth 1 https://github.com/summercards/action-library.git /tmp/action-library
cp -R /tmp/action-library/skill/action-library ~/.openclaw/workspace/skills/
```

也可以只下载单个文件：

```bash
curl -fsSL -o SKILL.md \
  https://raw.githubusercontent.com/summercards/action-library/main/skill/action-library/SKILL.md
```

### 方式二：连预览站一起

```bash
git clone https://github.com/summercards/action-library.git
cd action-library/web
python3 server.py          # 打开 http://127.0.0.1:8099
```

依赖只有三样：Python 3（标准库足够）、Blender（渲缩略图与套动作时用）、浏览器。前端 three.js 已随仓库提供，不联网也能跑。

### 更新

```bash
cd /tmp/action-library && git pull
cp -R skill/action-library ~/.openclaw/workspace/skills/
```

### 目录约定

预览站默认把动作库读作 `~/动作库`，放在别处时用环境变量指定：

```bash
ACLIB_HOME=/data/动作库 ACLIB_PORT=8100 python3 server.py
```

## 铁律（先记住这几条，能省掉大部分返工）

1. **原始下载包永不改名、永不修改、永不删除**。它是唯一能回滚的底。
2. **一条动作只能往上走，不能跳级**：原始下载 → 动作数据 → 整理后 → 导出。
3. **只有 `04_临时/` 可以随便删**，其余删除要人点头。
4. **文件名只用英文数字下划线**，中文备注写进总表。引擎和命令行遇到中文路径会给你惊喜。
5. **许可不明 = 不可商用**。不确定就按非商用处理，绝不进 `03_整理后` 和 `05_导出给引擎`。
6. **静态模型不算动作**。没动画的模型不收，收了就是占库。

## 目录结构

```text
~/动作库/
├── 00_说明与索引/     规则、总表、授权记录、库文件
├── 01_原始下载/       原封不动的压缩包，按来源分目录
├── 02_动作数据/       解开/转过格式的动作
├── 03_整理后/         已重定向到统一骨架、按用途分类的成品
├── 04_临时/           解压、试验、待删
├── 05_导出给引擎/     给 Godot / Unity 直接吃的成品
└── 90_网页系统/       预览站与工具（server.py、tools/）
```

## 流程一：搜集与下载

### 判断一个源值不值得下

| 条件 | 结论 |
|---|---|
| 有骨架或形变动画、能直接播 | 收 |
| 只有静态网格 | 跳过 |
| 要登录 / 要付费 / 要填邮箱换链接 | 跳过，记下原因 |
| 授权 CC0 / CC-BY / 公有领域 | 优先 |
| 仅研究用途 | 只进 `02_动作数据` |

### 素材源总表（实测地址，直接抄）

| 来源 | 地址 | 授权 | 实测状态 |
|---|---|---|---|
| CMU MoCap | `http://mocap.cs.cmu.edu/` | 免费科研/教学 | ✅ 2535 段 BVH 已入库 |
| SFU Mocap | `https://mocap.cs.sfu.ca/` | 免费科研，商用需问 | ✅ 44 段 BVH |
| LAFAN1 | `https://github.com/ubisoft/ubisoft-laforge-animation-dataset` | 研究用途，商用前查 `license.txt` | ✅ 77 段 BVH，统一骨架 |
| Quaternius 官方 | `https://quaternius.com/`<br>`https://quaternius.com/packs/ultimateanimatedanimals.html` | CC0 1.0 | ⚠️ 官网走 Google 网盘，直链拿不到 |
| Quaternius 镜像（**用这个**） | `https://quaternius.trebeljahr.com/animals_pack`<br>`https://quaternius.trebeljahr.com/dinosaurs_pack`<br>`https://quaternius.trebeljahr.com/easy_enemies_pack`<br>`https://quaternius.trebeljahr.com/fish_pack` | CC0 1.0 | ✅ 214 条带动画 glb，直链可取 |
| Khronos glTF 样例 | `https://github.com/KhronosGroup/glTF-Sample-Assets`<br>单件：`/tree/main/Models/Fox`、`/tree/main/Models/CesiumMan` | 多为 CC-BY 4.0，逐件看 | ✅ Fox / CesiumMan 可商用须署名 |
| three.js 示例 | `https://github.com/mrdoob/three.js/tree/dev/examples/models/gltf` | MIT | ✅ 马/火烈鸟/鹳/鹦鹉，**形变动画无骨骼** |
| Mixamo | `https://www.mixamo.com/` | Adobe 账号条款 | ⚠️ 需登录，已下 589 个 fbx |
| Kenney | `https://kenney.nl/assets` | CC0 | ⚠️ 下载按钮要人工点，脚本抓不到 |
| Bandai Namco 动作数据集 | `https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset` | 研究用途 | ⚠️ 约 300 MB，下载中 |

**已确认跳过**：Sketchfab、TurboSquid、CGTrader、Poly Pizza（要 key）——都要登录或付费，无人值守时进不去。

### 已验证可用的下载通道

**1. 能搜网页就用 DuckDuckGo 的 HTML 端点**（不需要 key）：

```bash
curl -s -A "Mozilla/5.0 (X11; Linux x86_64)" \
  "https://html.duckduckgo.com/html/?q=animated+animal+pack+cc0+glb" -o /tmp/s.html
grep -oE 'uddg=[^&"]+' /tmp/s.html | head -20   # 再 url 解码拿真实链接
```

**2. GitHub 仓库检索**（找开源动作包最有效）：

```bash
curl -s "https://api.github.com/search/repositories?q=<关键词>&sort=stars&per_page=20"
curl -s "https://api.github.com/repos/<owner>/<repo>/git/trees/HEAD?recursive=1"   # 列文件挑 .glb/.fbx/.bvh
```

仓库 tree 返回空就换分支：`.../git/trees/main?recursive=1`。

**3. three.js 官方示例（MIT，四足/鸟类，已验证）**：

```bash
base=https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf
# Horse.glb Flamingo.glb Stork.glb Parrot.glb
```

注意：这几个是 **morph target 形变动画**，没有骨骼。入库要标清楚，不能当骨骼动画用。

**4. itch.io 免费包**（免登录，但要过 CSRF）：

```bash
curl -sL -A "Mozilla/5.0" "https://<作者>.itch.io/<包名>" -o /tmp/p.html
grep -oE 'csrf_token" value="[^"]+' /tmp/p.html        # 拿 token
grep -oE 'upload_list_[0-9]+|"id":[0-9]{6,}' /tmp/p.html  # 拿 upload_id
curl -s -X POST -A "Mozilla/5.0" -d "csrf_token=<TOKEN>" \
  "https://<作者>.itch.io/<包名>/file/<UPLOAD_ID>?source=game_download"
# 返回 JSON 的 url 字段就是真实下载地址
```

**5. OpenGameArt**（服务端渲染，可抓）：`https://opengameart.org/art-search-advanced?keys=<词>&field_art_type_tid%5B%5D=5`（5=3D），条目页里挑 `sites/default/files/...zip`。

**6. Hugging Face 数据集**：`https://huggingface.co/api/datasets?search=<词>`。多数是姿态数据集不是动画片段，甄别后再下。

### 找非人形 / 怪兽 / 虫类的关键词

- **多足虫类**：beetle, ant, spider, scorpion, centipede, cockroach, crab, worm, wasp, insect swarm
- **怪兽**：dragon, wyvern, golem, troll, slime, undead, kaiju, beast, creature, monster
- **四足**：wolf, boar, deer, horse, cat, dog, fox, bear, raptor, dinosaur
- **水生 / 飞行**：shark, octopus, fish, bat, phoenix, bird
- **提高命中率的限定词**：`low poly`、`PSX`、`stylized`、`game ready`、`cc0`、`rigged`、`animation pack`

### 下载纪律

- 先 `curl -sIL -o /dev/null -w "%{http_code}"` 探一遍再批量下，别让脚本空转
- 单文件超 500 MB 先报备
- 总量设上限（如 5 GB），超了就分批
- 长任务：`setsid nohup ... < /dev/null &`，先建好日志目录
- 失败重试用指数退避，遇到 403/429 停一会儿，别硬刷

## 流程二：入库

六步，一步不省：

1. **落盘** → `01_原始下载/{来源}/`，文件名保持原样
2. **解压** → 解到 `04_临时/`，核对三件事：文件数对不对、动作时长正常吗、骨骼有没有名字
3. **校验** → `unzip -t`（压缩包）、`glTF` 头（glb）、`HIERARCHY`（bvh）、`Kaydara FBX Binary`（fbx）
4. **转格式** → 需要转的转（ASF/AMC → BVH、FBX → glTF），产物进 `02_动作数据/{格式}/`
5. **整理** → 统一骨架、剪首尾空帧、按用途分到 `03_整理后/{分类}/`
6. **登记** → `资源总表.md` 加一行，`授权与署名.md` 记来源/作者/授权

### 命名

`来源_动作_时长_授权.扩展名`，例：`Mixamo_run_1.2s_CC0.fbx`

### 状态口径（只用这六个）

`已下载` / `已解压` / `已转换` / `已整理` / `已入库` / `废弃`

状态变了改原来那行，不要新开一行。

## 流程三：分类打标

按维度打，不要混在一个标签里。人形库用六维（动作类型 / 速度 / 强度 / 对称性 / 用途 / 来源），生物库额外加一维 **形态**：

`四足` `六足` `八足` `多足` `蛇形无足` `鸟类双足` `水生` `龙类` `翼类` `软体` `未知`

并单独标 `人形=是/否`。

打标要写判断依据（20 字内），比如「八足外骨骼、根骨在胸、有爬行位移」。

**先切段再定性**：长动作按速度突变切段，再逐段判断，比整段贴一个标签准得多。

## 流程四：缩略图

复用 `tools/thumb_render.py`（Blender 无头渲染）+ `tools/make_thumbs.py`（批量）：

```bash
blender -b -t 4 --factory-startup -P tools/thumb_render.py -- <动作文件> <输出.png>
```

关键参数与坑：

- 取景：`frame_camera(pts, margin=2.1)`、`dist = size * margin * 0.82`——不然角色会顶出画面
- 360×360、Cycles、GPU（`OPTIX`/`CUDA`，用 `--factory-startup` 后按设备探测）
- 采样 12–16 + 降噪，够看且快
- 超时 45 秒，失败只标记不影响入库
- **贴图丢失会变成粉紫/纯白**，先渲染一张样张自己看一眼再跑批量

## 流程五：预览站

`90_网页系统/`：Python 3 标准库 HTTP 服务，单端口同时提供页面、API、文件。

```bash
python3 server.py        # 端口 8099（环境变量 ACLIB_PORT 可覆盖）
./start.sh / ./stop.sh   # 后台启停，pid 写 server.pid，日志 logs/server.log
```

路由分三组：

- 页面：`/`（动作库浏览）、`/rig.html`（套动作工作室）
- API：`/api/assets`、`/api/tags`、`/api/fav`、`/api/import`、`/api/health`、`/api/rig/*`
- 文件：`/files/{id}`（原文件）、`/api/rig/file?id=&what=glb|mp4|poster`

前端用 three.js（放 `vendor/`，用 importmap 引），BVH 走 `BVHLoader`、glb 走 `GLTFLoader`。

### 套动作（重定向）

`tools/retarget_job.py`：把库里的动作搬到上传的角色骨架上。

**算法要点**：逐帧按「源姿态 × 源静止姿逆 × 目标静止姿」换算再写关键帧。不要用世界空间 `COPY_ROTATION` 约束 + `nla.bake`——出来的骨架是扭的。

**踩过的坑**：

- **渲染粉紫/纯白 = 贴图没跟过来**。上传只传单个模型文件时，旁边的 `.fbm` 贴图目录会丢。解法：支持 zip 上传，模型和贴图一起压，解到独立文件夹，Blender 导入时自动找到。
- 骨骼匹配少于 12 根就判失败，别硬套
- 必须找到根骨（胯骨）才能定位角色；身高按胯骨世界高度对齐
- 预览镜头要跟随胯骨，否则跑步、跳跃时角色会跑出画面
- 纯动画 FBX（无网格）渲不出源模型，只能数值核对：比静止姿势差、逐帧最大偏差、平均偏差

## 流程六：验收（别信「应该没问题」）

1. **文件真的能打开**：按格式校验头字节
2. **Blender 抽样**：至少 5 条，确认有骨架、有动画帧数，把帧数写下来
3. **缩略图抽样看图**：不是空白、不是黑图、不是粉紫
4. **网页 200**：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8099/api/assets?page=1`
5. **页面能点通**：无头 Chromium 跑一遍，控制台异常必须为 0

无头浏览器截图必须开渲染，否则页面是空白：

```bash
chromium --headless=new --no-sandbox --disable-dev-shm-usage \
  --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader \
  --window-size=1600,900 --remote-debugging-port=9333 about:blank
```

## 常见坑（都真踩过）

- **Blender 5.2**：`m.data.vertices[::5]` 报 `TypeError: slice steps not supported`，要写 `list(m.data.vertices)[::5]`
- **远端 heredoc**：写在 `ssh "cat > /tmp/x.py <<EOF"` 里会静默失败，改成本地写完再 `scp`
- **zsh**：没有 `timeout`；glob 无匹配会报 `no matches found`，用 `find` 或显式文件名
- **Google Drive 文件夹**：目录页能抓到文件 ID，但 `uc?export=download` 常回空响应，别在这上面死磕，找镜像更省时间
- **Multipart 上传**：自己写解析要处理 boundary，别把库里二进制当文本切
- **端口**：先看谁在用（`ss -ltnp`），别抢已占端口

## 交付清单（做完必须能回答）

- 新增多少条、按来源分列
- 形态分布（四足/六足/八足/多足/蛇形/鸟类…各多少）
- 许可分布（CC0 / CC-BY / 非商用 / 不明）
- 总占用多少 MB / GB
- 哪些源因需登录或拿不到而跳过
- 缩略图失败几条
- 清单文件路径、原始包目录绝对路径

详细方案见 `docs/01_收集方案.md` 与 `docs/02_建库方案.md`。
