// 无头 Chromium 自检：打开 8099，检查卡片渲染、BVH/glTF 加载播放、标签接口
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';

const PORT = 9333;
const URL_APP = 'http://127.0.0.1:8099/';
const chrome = spawn('chromium', [
  '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
  '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--window-size=1600,900', `--remote-debugging-port=${PORT}`,
  '--user-data-dir=/tmp/aclib-cdp', 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
chrome.stderr.on('data', () => {});

async function waitDebugger() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return;
    } catch {}
    await sleep(250);
  }
  throw new Error('chromium 调试端口未就绪');
}

let seq = 0;
const pending = new Map();
const consoleMsgs = [];
const exceptions = [];
let ws;

function send(method, params = {}, sessionId) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}

async function evalJS(expression) {
  const r = await send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
    userGesture: true,
  });
  if (r.exceptionDetails) {
    return { __error: r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description || '') };
  }
  return r.result?.value;
}

async function waitFor(expr, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const v = await evalJS(expr);
    if (v) return v;
    await sleep(300);
  }
  return null;
}

const report = { ok: true, steps: [], errors: [] };
function step(name, data) { report.steps.push({ name, ...data }); }

try {
  await waitDebugger();
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      consoleMsgs.push({ type: m.params.type, text: m.params.args.map(a => a.value ?? a.description ?? '').join(' ').slice(0, 300) });
    }
    if (m.method === 'Runtime.exceptionThrown') {
      exceptions.push((m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text || '').slice(0, 400));
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      exceptions.push(`[log] ${m.params.entry.text}`.slice(0, 300));
    }
  };

  await send('Runtime.enable');
  await send('Log.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: URL_APP });
  await sleep(1500);

  const cardCount = await waitFor("document.querySelectorAll('.card').length > 0 && document.querySelectorAll('.card').length", 20000);
  step('卡片渲染', { cards: cardCount });
  if (!cardCount) throw new Error('页面没有渲染出卡片');

  const gl = await evalJS('window.__aclib ? window.__aclib.info.gl : null');
  step('WebGL', { version: gl });

  const pickAndPlay = async (name, ms = 3500) => {
    const clicked = await evalJS(`(() => {
      const cards = [...document.querySelectorAll('.card')];
      const c = cards.find(x => x.querySelector('h4')?.textContent.includes(${JSON.stringify(name)}));
      if (!c) return false;
      c.click(); return true;
    })()`);
    if (!clicked) throw new Error('找不到卡片 ' + name);
    await sleep(ms);
    return evalJS('window.__aclib.info');
  };

  const bvh1 = await pickAndPlay('walk1_subject1');
  step('BVH 加载', { hasMixer: bvh1.hasMixer, joints: bvh1.joints, bones: bvh1.bones, clipDuration: bvh1.clipDuration, time: bvh1.actionTime });
  const t1 = bvh1.actionTime;
  await sleep(1200);
  const bvh2 = await evalJS('window.__aclib.info');
  step('BVH 播放推进', { before: t1, after: bvh2.actionTime, advanced: bvh2.actionTime > t1 });
  if (!(bvh2.actionTime > t1)) report.ok = false, report.errors.push('BVH 时间未推进');

  const bvh3 = await pickAndPlay('dance1_subject1', 2500);
  step('BVH 第二条', { hasAction: bvh3.hasAction, joints: bvh3.joints, bones: bvh3.bones });

  const glb1 = await pickAndPlay('Fox', 3500);
  step('glTF 加载(Fox)', { children: glb1.rootChildren, hasAction: glb1.hasAction, clipDuration: glb1.clipDuration });
  await sleep(1000);
  const glb2 = await evalJS('window.__aclib.info');
  step('glTF 播放推进', { before: glb1.actionTime, after: glb2.actionTime, advanced: glb2.actionTime !== glb1.actionTime });

  const glb3 = await pickAndPlay('CesiumMan', 3000);
  step('glTF 加载(CesiumMan)', { children: glb3.rootChildren, hasAction: glb3.hasAction });

  // 标签 UI：给第一张卡点收藏
  const favRes = await evalJS(`(async () => {
    const card = document.querySelector('.card');
    card.querySelector('[data-act=fav]').click();
    await new Promise(r => setTimeout(r, 800));
    const before = await (await fetch('/api/assets/' + card.dataset.id)).json();
    card.querySelector('[data-act=fav]').click();
    await new Promise(r => setTimeout(r, 900));
    const d = await (await fetch('/api/assets/' + card.dataset.id)).json();
    return { id: card.dataset.id, before: before.favorite, after: d.favorite, flipped: before.favorite !== d.favorite, tags: d.tags.map(t => t.name) };
  })()`);
  step('收藏按钮落库', favRes);

  // 截图确认不是黑屏
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  step('截图', { base64KB: Math.round((shot.data?.length || 0) / 1024) });

  step('控制台错误', { consoleErrors: consoleMsgs.filter(m => m.type === 'error'), exceptions });
  if (exceptions.length) report.ok = false;
} catch (e) {
  report.ok = false;
  report.errors.push(String(e.message || e));
} finally {
  try { ws?.close(); } catch {}
  chrome.kill('SIGKILL');
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}
