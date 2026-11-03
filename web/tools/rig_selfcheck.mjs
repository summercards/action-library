// 套动作页面自检：打开 /rig.html，验证模型列表、动作列表、选中联动、发起任务，并截图
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { writeFileSync } from 'node:fs';

const PORT = 9344;
const URL_APP = 'http://127.0.0.1:8099/rig.html';
const chrome = spawn('chromium', [
  '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
  '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--window-size=1500,950', `--remote-debugging-port=${PORT}`,
  '--user-data-dir=/tmp/aclib-cdp-rig', 'about:blank',
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
const exceptions = [];
const consoleErr = [];
let ws;

function send(method, params = {}, sessionId) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}

async function evalJS(expression) {
  const r = await send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true, userGesture: true,
  });
  if (r.exceptionDetails) {
    return { __error: r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description || '') };
  }
  return r.result?.value;
}

async function waitFor(expr, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const v = await evalJS(expr);
    if (v) return v;
    await sleep(300);
  }
  return null;
}

const report = { ok: true, steps: [], errors: [] };

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
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErr.push(m.params.args.map(a => a.value ?? a.description ?? '').join(' ').slice(0, 300));
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
  await sleep(1800);

  const title = await evalJS('document.title');
  report.steps.push({ name: '页面打开', title });

  const nM = await waitFor("document.querySelectorAll('#mlist .mitem').length || null", 15000);
  report.steps.push({ name: '模型列表', score: nM });
  if (!nM) { report.ok = false; report.errors.push('模型列表是空的'); }

  const nA = await waitFor("document.querySelectorAll('#alist .aitem').length || null", 20000);
  report.steps.push({ name: '动作列表', score: nA });
  if (!nA) { report.ok = false; report.errors.push('动作列表是空的'); }

  // 选模型
  const mClick = await evalJS(`(() => {
    const el = document.querySelector('#mlist .mitem');
    if (!el) return null;
    el.click();
    return el.querySelector('.nm').textContent.trim();
  })()`);
  await sleep(600);
  report.steps.push({ name: '选中模型', value: mClick });

  // 搜 Walking 并选第一条
  await evalJS(`(() => {
    const q = document.querySelector('#q');
    q.value = 'Walking';
    q.dispatchEvent(new Event('input', {bubbles:true}));
    return true;
  })()`);
  await sleep(1800);
  const aClick = await evalJS(`(() => {
    const el = document.querySelector('#alist .aitem');
    if (!el) return null;
    el.click();
    return el.querySelector('.nm').textContent.trim();
  })()`);
  await sleep(500);
  report.steps.push({ name: '选中动作', value: aClick });

  const pickText = await evalJS("document.querySelector('#pick').textContent");
  const runDisabled = await evalJS("document.querySelector('#run').disabled");
  report.steps.push({ name: '联动', pick: pickText, runEnabled: !runDisabled });
  if (runDisabled) { report.ok = false; report.errors.push('选了模型和动作，按钮还是灰的'); }

  // 截图（选择状态）
  const shot1 = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync('/tmp/rig_page_list.png', Buffer.from(shot1.data, 'base64'));

  // 点「套上试试」，看进度是否推进
  await evalJS("document.querySelector('#run').click(); true");
  const progressed = await waitFor(
    "(() => { const w = document.querySelector('#bar').style.width; const m = document.querySelector('#msg').textContent; return (parseFloat(w) > 2 || /渲染|准备|匹配/.test(m)) ? (w + ' | ' + m) : null; })()",
    60000);
  report.steps.push({ name: '点了开始', progress: progressed });
  if (!progressed) { report.ok = false; report.errors.push('点了套动作没有反应'); }

  // 等它渲染一部分，截个进行中的图
  await sleep(6000);
  const shot2 = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync('/tmp/rig_page_run.png', Buffer.from(shot2.data, 'base64'));

  const jobs = await evalJS("fetch('/api/rig/jobs').then(r=>r.json()).then(d=>JSON.stringify(d.items[0]||{}))");
  report.steps.push({ name: '最新任务', job: jobs });

  if (exceptions.length) { report.ok = false; report.errors.push(...exceptions); }
  if (consoleErr.length) report.steps.push({ name: '控制台报错', list: consoleErr.slice(0, 5) });
} catch (e) {
  report.ok = false;
  report.errors.push('异常：' + e.message);
} finally {
  console.log('REPORT ' + JSON.stringify(report, null, 1));
  try { ws && ws.close(); } catch {}
  chrome.kill('SIGKILL');
  process.exit(0);
}
