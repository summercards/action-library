import * as THREE from 'three';
import { BVHLoader } from 'three/addons/loaders/BVHLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

/* ------------------------------ 状态 ------------------------------ */
const state = {
  items: [],
  total: 0,
  tags: [],
  stats: null,
  q: '',
  source: null,
  tag: null,
  fav: false,
  selected: null,
  tagModalAsset: null,
};

const $ = (id) => document.getElementById(id);

function toast(msg, ms = 1800) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const ct = r.headers.get('Content-Type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || `${r.status} ${r.statusText}`);
  return data;
}

/* ------------------------------ 工具 ------------------------------ */
function fmtDur(sec) {
  if (!sec || sec <= 0) return '—';
  if (sec < 60) return sec.toFixed(2) + 's';
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------ 左侧栏 ------------------------------ */
async function loadStats() {
  state.stats = await api('/api/stats');
  $('totalBadge').textContent = `${state.stats.total} 条`;
  const ul = $('sourceList');
  const rows = [{ name: '全部', c: state.stats.total, raw: null }].concat(
    state.stats.sources.map((s) => ({ name: s.source || '未标注', c: s.c, raw: s.source }))
  );
  ul.innerHTML = rows
    .map(
      (r) => `<li class="${state.source === r.raw || (r.raw === null && state.source === null) ? 'on' : ''}" data-source="${esc(r.raw ?? '')}" data-all="${r.raw === null ? 1 : 0}">
        <span>${esc(r.name)}</span><span class="n">${r.c}</span></li>`
    )
    .join('');
  ul.querySelectorAll('li').forEach((li) => {
    li.onclick = () => {
      state.source = li.dataset.all === '1' ? null : li.dataset.source;
      state.tag = null;
      loadStats();
      loadAssets();
    };
  });
}

async function loadTags() {
  const d = await api('/api/tags');
  state.tags = d.items;
  const ul = $('tagList');
  if (!state.tags.length) {
    ul.innerHTML = '<li class="muted">还没有标签</li>';
    return;
  }
  const groups = {};
  for (const t of state.tags) (groups[t.category || '自定义'] ||= []).push(t);
  ul.innerHTML = Object.entries(groups)
    .map(
      ([cat, list]) =>
        `<li class="muted" style="padding:2px 8px;font-size:10px;letter-spacing:.06em">${esc(cat)}</li>` +
        list
          .map(
            (t) => `<li class="${state.tag === String(t.id) ? 'on' : ''}" data-tag="${t.id}">
              <span>${esc(t.name)}</span><span class="n">${t.c}</span></li>`
          )
          .join('')
    )
    .join('');
  ul.querySelectorAll('li[data-tag]').forEach((li) => {
    li.onclick = () => {
      state.tag = state.tag === li.dataset.tag ? null : li.dataset.tag;
      state.source = null;
      loadStats();
      loadTags();
      loadAssets();
    };
  });
}

/* ------------------------------ 卡片网格 ------------------------------ */
async function loadAssets() {
  const p = new URLSearchParams();
  if (state.q) p.set('q', state.q);
  if (state.source) p.set('source', state.source);
  if (state.tag) p.set('tag', state.tag);
  if (state.fav) p.set('favorite', '1');
  p.set('limit', '500');
  const d = await api('/api/assets?' + p.toString());
  state.items = d.items;
  state.total = d.total;
  renderGrid();
  renderActiveFilters();
}

function renderActiveFilters() {
  const parts = [];
  if (state.q) parts.push(`搜索：${state.q}`);
  if (state.source) parts.push(`来源：${state.source}`);
  if (state.tag) {
    const t = state.tags.find((x) => String(x.id) === state.tag);
    parts.push('标签：' + (t ? t.name : state.tag));
  }
  if (state.fav) parts.push('只看收藏');
  const box = $('activeFilters');
  box.innerHTML = parts.map((p) => `<span class="chip-active">${esc(p)} ✕</span>`).join('');
  box.querySelectorAll('.chip-active').forEach((el, i) => {
    el.onclick = () => {
      const key = ['q', 'source', 'tag', 'fav'][i];
      state[key] = key === 'fav' ? false : key === 'q' ? '' : null;
      if (key === 'q') $('search').value = '';
      if (key === 'fav') $('favFilter').classList.remove('on');
      loadStats();
      loadTags();
      loadAssets();
    };
  });
}

function renderGrid() {
  const grid = $('grid');
  $('empty').hidden = state.items.length > 0;
  grid.innerHTML = state.items
    .map((a) => {
      const icons = { bvh: '🦴', glb: '🧍', gltf: '🧍', fbx: '📦' };
      const thumb = a.thumb && a.thumb.startsWith('/')
        ? `<img src="${esc(a.thumb)}" alt="" loading="lazy">`
        : `<span class="ph">${icons[a.format] || '🎞'}</span>`;
      const tags = (a.tags || [])
        .slice(0, 4)
        .map((t) => `<span class="chip">${esc(t.name)}</span>`)
        .join('');
      return `<article class="card ${state.selected === a.id ? 'sel' : ''}" data-id="${a.id}">
        <div class="thumb">${thumb}<span class="fmt">${esc(a.format)}</span><span class="dur">${fmtDur(a.duration)}</span></div>
        <div class="card-body">
          <h4 title="${esc(a.name)}">${esc(a.name)}</h4>
          <div class="sub">${esc(a.code)} · ${esc(a.source || '')}</div>
          <div class="sub">${a.bones ? a.bones + ' 骨 · ' : ''}${a.frames ? a.frames + ' 帧' : a.animations ? a.animations + ' 段动画' : ''}</div>
          <div class="chips">${tags}</div>
        </div>
        <div class="card-actions">
          <button class="fav ${a.favorite ? 'on' : ''}" data-act="fav">${a.favorite ? '★ 已收藏' : '☆ 收藏'}</button>
          <button data-act="tag">＋ 标签</button>
        </div>
      </article>`;
    })
    .join('');

  grid.querySelectorAll('.card').forEach((card) => {
    const id = Number(card.dataset.id);
    card.onclick = (ev) => {
      const act = ev.target.closest('button')?.dataset.act;
      if (act === 'fav') return toggleFav(id);
      if (act === 'tag') return openTagModal(id);
      selectAsset(id);
    };
  });
}

/* ------------------------------ 标签 / 收藏 ------------------------------ */
async function toggleFav(id) {
  const a = state.items.find((x) => x.id === id);
  if (!a) return;
  const d = await api(`/api/assets/${id}/favorite`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ favorite: !a.favorite }),
  });
  a.favorite = d.favorite;
  if (state.fav && !a.favorite) return loadAssets();
  loadStats();
  renderGrid();
}

function openTagModal(id) {
  const a = state.items.find((x) => x.id === id);
  if (!a) return;
  state.tagModalAsset = a;
  $('tagModalTitle').textContent = `标签 · ${a.name}`;
  $('tagModal').hidden = false;
  renderTagModal();
}

function renderTagModal() {
  const a = state.tagModalAsset;
  if (!a) return;
  const mine = new Set((a.tags || []).map((t) => t.id));
  const groups = {};
  for (const t of state.tags) (groups[t.category || '自定义'] ||= []).push(t);
  const html = Object.entries(groups)
    .map(
      ([cat, list]) => `<div class="tag-group"><h5>${esc(cat)}</h5>` +
        list
          .map(
            (t) => `<label class="tag-item"><input type="checkbox" data-tag="${t.id}" ${mine.has(t.id) ? 'checked' : ''}><span>${esc(t.name)}</span></label>`
          )
          .join('') + '</div>'
    )
    .join('');
  $('tagModalBody').innerHTML = html || '<div class="muted">还没有标签，下面输入框新建</div>';
  $('tagModalBody').querySelectorAll('input[type=checkbox]').forEach((cb) => {
    cb.onchange = async () => {
      const tid = Number(cb.dataset.tag);
      try {
        if (cb.checked) {
          await api(`/api/assets/${a.id}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tagId: tid }),
          });
        } else {
          await api(`/api/assets/${a.id}/tags/${tid}`, { method: 'DELETE' });
        }
        await syncTagsOf(a);
        await loadTags();
        renderGrid();
        renderMeta();
      } catch (e) {
        toast('标签操作失败：' + e.message);
      }
    };
  });
}

async function syncTagsOf(a) {
  const d = await api(`/api/assets/${a.id}`);
  a.tags = d.tags;
}

async function addNewTag() {
  const a = state.tagModalAsset;
  const name = $('newTagInput').value.trim();
  if (!a || !name) return;
  try {
    await api(`/api/assets/${a.id}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    $('newTagInput').value = '';
    await syncTagsOf(a);
    await loadTags();
    renderTagModal();
    renderGrid();
    renderMeta();
    toast('已添加标签：' + name);
  } catch (e) {
    toast('添加失败：' + e.message);
  }
}

/* ------------------------------ 3D 视口 ------------------------------ */
const canvas = $('cv');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0d11);

const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 2000);
const orbit = { theta: 0.75, phi: 1.30, radius: 3.2, target: new THREE.Vector3(0, 0.9, 0) };

const grid = new THREE.GridHelper(20, 40, 0x2a3340, 0x1a2028);
grid.position.y = 0;
scene.add(grid);

scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x20242c, 1.6));
const dir = new THREE.DirectionalLight(0xffffff, 1.4);
dir.position.set(3, 6, 4);
scene.add(dir);
const fill = new THREE.DirectionalLight(0x88aaff, 0.6);
fill.position.set(-4, 3, -3);
scene.add(fill);

const modelRoot = new THREE.Group();
scene.add(modelRoot);
// 骨骼辅助线与关节球放这一层：它们用世界坐标绘制，不能跟着 modelRoot 缩放
const overlay = new THREE.Group();
scene.add(overlay);

let mixer = null;
let action = null;
let currentRootBone = null;
let playing = true;
let speed = 1;
let follow = false;
let jointSpheres = [];
let helper = null;
let expected = null;
const clock = new THREE.Clock();

function clearModel() {
  if (mixer) { mixer.stopAllAction(); mixer = null; }
  action = null;
  currentRootBone = null;
  jointSpheres = [];
  helper = null;
  for (const root of [modelRoot, overlay]) {
    while (root.children.length) {
      const c = root.children.pop();
      c.traverse?.((o) => {
        if (o.geometry) o.geometry.dispose?.();
      });
    }
  }
  modelRoot.position.set(0, 0, 0);
  modelRoot.scale.setScalar(1);
  orbit.target.set(0, 0.9, 0);
  orbit.radius = 3.2;
  updateCamera();
}

function boneBox(bones) {
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  modelRoot.updateMatrixWorld(true);
  for (const b of bones) box.expandByPoint(b.getWorldPosition(v));
  return box;
}

function fitToView(box) {
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  if (!isFinite(maxDim) || maxDim <= 0) return;
  const s = 1.8 / maxDim;
  modelRoot.scale.setScalar(s);
  modelRoot.updateMatrixWorld(true);
}

function placeOnGround(bones) {
  const box = bones ? boneBox(bones) : new THREE.Box3().setFromObject(modelRoot);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  modelRoot.position.x -= c.x;
  modelRoot.position.z -= c.z;
  modelRoot.position.y -= box.min.y;
  modelRoot.updateMatrixWorld(true);
  orbit.target.set(0, 0.95, 0);
  orbit.radius = 3.2;
  updateCamera();
}

function makeJointSpheres(bones, radius) {
  // radius 是世界单位；球挂在 overlay 上，不被 modelRoot 的缩放二次缩小
  const geo = new THREE.SphereGeometry(radius, 12, 10);
  const mat = new THREE.MeshBasicMaterial({ color: 0x7fe3ff });
  for (const b of bones) {
    const m = new THREE.Mesh(geo, mat);
    b.getWorldPosition(m.position);
    overlay.add(m);
    jointSpheres.push({ mesh: m, bone: b });
  }
}

function loadBVH(url, asset) {
  return new Promise((resolve, reject) => {
    new BVHLoader().load(
      url,
      (res) => {
        const bones = res.skeleton.bones;
        modelRoot.add(bones[0]);
        currentRootBone = bones[0];
        helper = new THREE.SkeletonHelper(bones[0]);
        helper.material.color.set(0x8fe3ff);
        helper.material.transparent = true;
        helper.material.opacity = 0.9;
        overlay.add(helper);
        // 先应用第一帧姿势，再按真实姿势量身高、落地
        mixer = new THREE.AnimationMixer(bones[0]);
        action = mixer.clipAction(res.clip);
        action.play();
        mixer.update(0.0001);
        let box = boneBox(bones);
        fitToView(box);
        box = boneBox(bones);
        const size = box.getSize(new THREE.Vector3());
        makeJointSpheres(bones, Math.max(size.y * 0.015, 0.012));
        placeOnGround(bones);
        if (!playing) action.paused = true;
        action.timeScale = speed;
        $('loopBtn').classList.contains('on')
          ? action.setLoop(THREE.LoopRepeat, Infinity)
          : action.setLoop(THREE.LoopOnce, 1);
        follow = true;
        resolve();
      },
      undefined,
      (e) => reject(e)
    );
  });
}

function loadGLTF(url, asset) {
  return new Promise((resolve, reject) => {
    new GLTFLoader().load(
      url,
      (gltf) => {
        modelRoot.add(gltf.scene);
        gltf.scene.traverse((o) => {
          if (o.isMesh) o.frustumCulled = false;
          if (o.isSkinnedMesh) o.frustumCulled = false;
        });
        if (gltf.animations && gltf.animations.length) {
          mixer = new THREE.AnimationMixer(gltf.scene);
          action = mixer.clipAction(gltf.animations[0]);
          action.play();
          mixer.update(0.0001);
        }
        const box = new THREE.Box3().setFromObject(gltf.scene);
        fitToView(box);
        placeOnGround(null);
        if (action) {
          if (!playing) action.paused = true;
          action.timeScale = speed;
          $('loopBtn').classList.contains('on')
            ? action.setLoop(THREE.LoopRepeat, Infinity)
            : action.setLoop(THREE.LoopOnce, 1);
        }
        follow = false;
        resolve();
      },
      undefined,
      (e) => reject(e)
    );
  });
}

async function selectAsset(id) {
  const a = state.items.find((x) => x.id === id);
  if (!a) return;
  state.selected = id;
  document.querySelectorAll('.card').forEach((c) => c.classList.toggle('sel', Number(c.dataset.id) === id));
  renderMeta();
  $('hud').textContent = `${a.name}（${a.format.toUpperCase()}）`;
  $('loading').hidden = false;
  clearModel();
  try {
    if (a.format === 'bvh') await loadBVH(a.files_url, a);
    else if (a.format === 'glb' || a.format === 'gltf') await loadGLTF(a.files_url, a);
    else {
      $('hud').textContent = '该格式（FBX）暂不支持网页预览';
      $('loading').hidden = true;
      return;
    }
    $('playBtn').textContent = playing ? '⏸' : '▶';
    $('scrub').value = 0;
  } catch (e) {
    console.error(e);
    $('hud').textContent = '加载失败：' + (e.message || e.type || '未知错误');
    toast('加载失败：' + (e.message || e.type || '未知错误'), 3000);
  } finally {
    $('loading').hidden = true;
  }
}

function renderMeta() {
  const a = state.items.find((x) => x.id === state.selected);
  if (!a) { $('meta').innerHTML = '<div class="muted">未选择动作</div>'; return; }
  const rows = [
    ['编号', a.code],
    ['名称', a.name],
    ['格式', a.format.toUpperCase()],
    ['来源', a.source || '—'],
    ['授权', a.license || '—'],
    ['时长', fmtDur(a.duration)],
    ['帧数 / 帧率', a.format === 'bvh' ? `${a.frames} 帧 @ ${a.fps} fps` : a.animations ? `${a.animations} 段动画` : '—'],
    ['骨骼 / 节点', `${a.bones || 0} / ${a.nodes || 0}`],
    ['体积', (a.size_bytes / 1024 / 1024).toFixed(2) + ' MB'],
    ['路径', a.rel_path],
  ];
  $('meta').innerHTML =
    rows.map(([k, v]) => `<div class="row"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join('') +
    `<div class="tagline">${(a.tags || [])
      .map((t) => `<span class="pill" data-tag-pill="${t.id}">${esc(t.name)} ✕</span>`)
      .join('') || '<span class="muted">无标签</span>'}</div>`;
  $('meta').querySelectorAll('[data-tag-pill]').forEach((p) => {
    p.onclick = async () => {
      await api(`/api/assets/${a.id}/tags/${p.dataset.tagPill}`, { method: 'DELETE' });
      await syncTagsOf(a);
      await loadTags();
      renderGrid();
      renderMeta();
    };
  });
}

/* 相机 */
function updateCamera() {
  const { radius, theta, phi, target } = orbit;
  const off = new THREE.Vector3(
    radius * Math.sin(phi) * Math.sin(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.cos(theta)
  );
  camera.position.copy(target).add(off);
  camera.lookAt(target);
}

let dragging = false, lastX = 0, lastY = 0;
canvas.addEventListener('pointerdown', (e) => {
  dragging = true; lastX = e.clientX; lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointerup', (e) => { dragging = false; });
canvas.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  const dx = e.clientX - lastX, dy = e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  orbit.theta -= dx * 0.006;
  orbit.phi = Math.min(1.55, Math.max(0.12, orbit.phi - dy * 0.005));
});
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  orbit.radius = Math.min(30, Math.max(0.5, orbit.radius * Math.exp(e.deltaY * 0.0012)));
}, { passive: false });

function resize() {
  const el = $('viewport');
  const w = el.clientWidth, h = el.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe($('viewport'));

/* 播放控制 */
$('playBtn').onclick = () => {
  playing = !playing;
  if (action) action.paused = !playing;
  $('playBtn').textContent = playing ? '⏸' : '▶';
};
$('loopBtn').onclick = () => {
  const on = $('loopBtn').classList.toggle('on');
  if (action) on ? action.setLoop(THREE.LoopRepeat, Infinity) : action.setLoop(THREE.LoopOnce, 1);
};
$('speed').onchange = () => {
  speed = Number($('speed').value);
  if (action) action.timeScale = speed;
};
let scrubbing = false;
$('scrub').addEventListener('pointerdown', () => (scrubbing = true));
$('scrub').addEventListener('pointerup', () => (scrubbing = false));
$('scrub').addEventListener('input', () => {
  if (!mixer || !action) return;
  const dur = action.getClip().duration || 0;
  const t = (Number($('scrub').value) / 1000) * dur;
  action.time = Math.min(t, dur);
  mixer.update(0);
});

/* 主循环 */
const tmpV = new THREE.Vector3();
function tick() {
  requestAnimationFrame(tick);
  const dt = Math.min(clock.getDelta(), 0.1);
  if (mixer && action && playing) mixer.update(dt);
  if (mixer && action) {
    const dur = action.getClip().duration || 0.0001;
    $('timeLabel').textContent = `${action.time.toFixed(2)} / ${dur.toFixed(2)} s`;
    if (!scrubbing) $('scrub').value = String(Math.round((action.time / dur) * 1000));
  }
  if (jointSpheres.length) {
    modelRoot.updateMatrixWorld(true);
    for (const j of jointSpheres) {
      j.bone.getWorldPosition(j.mesh.position);
    }
  }
  if (follow && currentRootBone) {
    // 根位移会让角色走出画面：镜头紧跟根骨，角色始终留在视口中央
    currentRootBone.getWorldPosition(tmpV);
    orbit.target.x += (tmpV.x - orbit.target.x) * 0.35;
    orbit.target.z += (tmpV.z - orbit.target.z) * 0.35;
  }
  updateCamera();
  renderer.render(scene, camera);
}

/* ------------------------------ 交互 ------------------------------ */
let searchTimer = null;
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = $('search').value.trim();
    loadAssets();
  }, 260);
});
$('favFilter').onclick = () => {
  state.fav = !state.fav;
  $('favFilter').classList.toggle('on', state.fav);
  $('favFilter').textContent = state.fav ? '★ 只看收藏' : '☆ 只看收藏';
  loadAssets();
};
$('reindexBtn').onclick = async () => {
  toast('正在重新扫描动作文件…', 4000);
  try {
    const d = await api('/api/reindex', { method: 'POST' });
    toast(d.ok ? '索引完成：' + (d.stdout.split('\n')[0] || '') : '索引失败，看服务日志', 3500);
    await Promise.all([loadStats(), loadTags(), loadAssets()]);
  } catch (e) {
    toast('索引失败：' + e.message);
  }
};
$('tagModalClose').onclick = () => { $('tagModal').hidden = true; state.tagModalAsset = null; };
$('tagModal').onclick = (e) => { if (e.target.id === 'tagModal') { $('tagModal').hidden = true; } };
$('newTagBtn').onclick = addNewTag;
$('newTagInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') addNewTag(); });

/* ------------------------------ 上传 ------------------------------ */
const OK_EXTS = ['.glb', '.gltf', '.fbx', '.bvh'];
let dragDepth = 0;

function humanSize(n) {
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n >= 1024) return Math.round(n / 1024) + ' KB';
  return n + ' 字节';
}

function friendlyHttp(status) {
  if (status === 413) return '文件太大，服务器拒收了。';
  if (status === 0) return '连不上服务器，检查服务是不是停了。';
  if (status === 502 || status === 504) return '服务器忙不过来，稍等一会儿再传。';
  return '服务器返回异常（' + status + '），看服务日志。';
}

function addUploadRow(file) {
  const panel = $('uploadPanel');
  panel.hidden = false;
  const row = document.createElement('div');
  row.className = 'upload-row';
  row.innerHTML = `<div class="upload-name"></div>
    <div class="upload-bar"><i></i></div>
    <div class="upload-state">排队中…</div>`;
  row.querySelector('.upload-name').textContent = file.name + ' · ' + humanSize(file.size);
  row.querySelector('.upload-name').title = file.name;
  $('uploadList').prepend(row);
  return { row, bar: row.querySelector('.upload-bar i'), state: row.querySelector('.upload-state') };
}

function uploadOne(file) {
  const task = addUploadRow(file);
  return new Promise((resolve) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.timeout = 180000;

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
      task.bar.style.width = pct + '%';
      task.state.textContent = '上传中 ' + pct + '%';
    };
    xhr.upload.onload = () => {
      task.bar.style.width = '100%';
      task.state.textContent = '已送达，正在校验并生成缩略图…';
    };
    xhr.onload = () => {
      let d = {};
      try { d = JSON.parse(xhr.responseText || '{}'); } catch (e) { d = {}; }
      if (xhr.status >= 200 && xhr.status < 300 && d.ok) {
        task.row.classList.add('ok');
        const hasThumb = d.thumb && String(d.thumb).startsWith('/');
        task.state.textContent = hasThumb ? '完成 · 缩略图已生成' : '完成 · 缩略图待补';
        if (hasThumb && d.asset) toast('已入库：' + d.asset.name + '（' + d.asset.code + '）', 3000);
        else if (d.notice) toast(d.notice, 5000);
        resolve(true);
      } else {
        task.row.classList.add('bad');
        task.bar.style.width = '100%';
        task.state.textContent = d.error || friendlyHttp(xhr.status);
        resolve(false);
      }
    };
    xhr.onerror = () => {
      task.row.classList.add('bad');
      task.state.textContent = friendlyHttp(0);
      resolve(false);
    };
    xhr.ontimeout = () => {
      task.row.classList.add('bad');
      task.state.textContent = '等太久没响应（3 分钟），先别重复传，看看服务日志。';
      resolve(false);
    };
    xhr.send(fd);
  });
}

async function uploadFiles(list) {
  const files = Array.from(list || []);
  if (!files.length) return;
  const good = [];
  for (const f of files) {
    const ext = ('.' + f.name.split('.').pop()).toLowerCase();
    if (!OK_EXTS.includes(ext)) {
      toast(`「${f.name}」不是动作文件，只收 glb / gltf / fbx / bvh。`, 4000);
      continue;
    }
    good.push(f);
  }
  if (!good.length) return;
  $('uploadBtn').disabled = true;
  let ok = 0, bad = 0;
  for (const f of good) {
    const fine = await uploadOne(f);
    fine ? ok++ : bad++;
  }
  $('uploadBtn').disabled = false;
  await Promise.all([loadStats(), loadTags(), loadAssets()]);
  if (bad === 0) toast(`上传完成：${ok} 个文件已入库。`, 3000);
  else toast(`上传结束：成功 ${ok} 个，失败 ${bad} 个（失败原因见上传面板）。`, 6000);
}

$('uploadBtn').onclick = () => $('fileInput').click();
$('fileInput').onchange = (e) => { uploadFiles(e.target.files); e.target.value = ''; };
$('uploadClose').onclick = () => {
  $('uploadPanel').hidden = true;
  $('uploadList').innerHTML = '';
};

document.addEventListener('dragenter', (e) => {
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
  dragDepth++;
  $('dropHint').hidden = false;
});
document.addEventListener('dragover', (e) => { e.preventDefault(); });
document.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $('dropHint').hidden = true;
});
document.addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  $('dropHint').hidden = true;
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
    uploadFiles(e.dataTransfer.files);
  }
});

/* 调试钩子（供无头浏览器自检，不影响页面） */
window.__aclib = {
  THREE, scene, camera, renderer, modelRoot,
  get state() { return state; },
  get info() {
    return {
      playing, speed,
      hasMixer: !!mixer,
      hasAction: !!action,
      actionTime: action ? action.time : null,
      clipDuration: action ? action.getClip().duration : null,
      rootChildren: modelRoot.children.length,
      joints: jointSpheres.length,
      bones: currentRootBone ? (function(){let n=0;currentRootBone.traverse(()=>n++);return n;})() : 0,
      target: orbit.target.toArray(),
      radius: orbit.radius,
      gl: renderer.getContext() ? renderer.getContext().getParameter(renderer.getContext().VERSION) : null,
    };
  },
  readPixels() {
    renderer.render(scene, camera);
    const gl = renderer.getContext();
    const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const buf = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    let bright = 0, colored = 0, minX = 1e9, maxX = -1, minY = 1e9, maxY = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        const r = buf[i], g = buf[i + 1], b = buf[i + 2];
        if (r + g + b > 200) {
          bright++;
          if (b > 100 && g > 90) {
            colored++;
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
          }
        }
      }
    }
    return { w, h, bright, colored, box: [minX, minY, maxX, maxY] };
  },
  probe() {
    const wp = (o) => { const v = new THREE.Vector3(); o.getWorldPosition(v); return v.toArray().map(n => +n.toFixed(3)); };
    let bmin = [1e9,1e9,1e9], bmax = [-1e9,-1e9,-1e9];
    if (currentRootBone) {
      currentRootBone.traverse((o) => {
        if (!o.isBone) return;
        const p = wp(o);
        for (let i = 0; i < 3; i++) { bmin[i] = Math.min(bmin[i], p[i]); bmax[i] = Math.max(bmax[i], p[i]); }
      });
    }
    const ndc = (() => {
      if (!currentRootBone) return null;
      const v = new THREE.Vector3(); currentRootBone.getWorldPosition(v);
      v.project(camera);
      return v.toArray().map(n => +n.toFixed(3));
    })();
    return {
      modelScale: modelRoot.scale.x, modelPos: modelRoot.position.toArray(),
      cam: camera.position.toArray().map(n => +n.toFixed(3)),
      target: orbit.target.toArray().map(n => +n.toFixed(3)),
      radius: orbit.radius, ndcRoot: ndc,
      boneMin: bmin, boneMax: bmax,
      render: { ...renderer.info.render },
      sceneChildren: scene.children.length,
      modelChildren: modelRoot.children.length,
      helperVisible: helper ? helper.visible : null,
      camMatrixOK: camera.matrixWorld.elements.every(Number.isFinite),
    };
  },
};

/* ------------------------------ 启动 ------------------------------ */
(async function init() {
  resize();
  tick();
  try {
    await Promise.all([loadStats(), loadTags()]);
    await loadAssets();
  } catch (e) {
    toast('加载失败，检查服务是否运行：' + e.message, 5000);
  }
})();
