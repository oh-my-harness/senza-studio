const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ channel: 'chromium' });
  const p = await b.newPage({ viewport: { width: 1400, height: 880 } });
  const bad = [];
  p.on('response', r => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().replace('http://127.0.0.1:8000','')}`); });
  p.on('pageerror', e => bad.push('pageerror: ' + String(e).slice(0,140)));
  const resp = await p.goto('http://127.0.0.1:8000/', { waitUntil: 'domcontentloaded' });
  console.log('  主文档状态:', resp.status());
  await p.waitForTimeout(3000);
  console.log('  页面标题:', await p.title());
  console.log('  DAG 节点数:', await p.locator('.react-flow__node').count());
  console.log('  页面可见文字(前 200):', (await p.locator('body').innerText()).slice(0,200).replace(/\n/g,' | '));
  console.log('  4xx/5xx 或错误:', bad.length ? bad : '无');
  await p.screenshot({ path: process.env.OUT + '/user8000.png' });
  await b.close();
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
