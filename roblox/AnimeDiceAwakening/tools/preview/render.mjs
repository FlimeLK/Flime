// Рендерить скріни сцени (scene.json з export_scene.py) у headless Chromium через three.js.
// Використання:
//   node tools/preview/render.mjs <scene.json> <views.json> <out-dir>
// Потрібні пакети three і playwright-core (npm i three playwright-core) — шлях до node_modules
// задає NODE_MODULES (за замовчуванням ./node_modules), Chromium — CHROMIUM (/opt/pw-browsers/...).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const [scenePath, viewsPath, outDir] = process.argv.slice(2);
const here = path.dirname(fileURLToPath(import.meta.url));
const nodeModules = process.env.NODE_MODULES || path.resolve('node_modules');
const views = JSON.parse(fs.readFileSync(viewsPath, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });

const TYPES = { '.js': 'text/javascript', '.html': 'text/html', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  let file;
  if (url === '/' || url === '/viewer.html') file = path.join(here, 'viewer.html');
  else if (url === '/scene.json') file = path.resolve(scenePath);
  else if (url.startsWith('/three/')) file = path.join(nodeModules, 'three', url.slice('/three/'.length));
  if (!file || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(0, r));
const port = server.address().port;

const executablePath = process.env.CHROMIUM || fs.readdirSync('/opt/pw-browsers')
  .filter(d => d.startsWith('chromium-')).map(d => `/opt/pw-browsers/${d}/chrome-linux/chrome`).find(p => fs.existsSync(p));
const browser = await chromium.launch({ executablePath, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.on('console', m => { if (m.type() === 'error') console.error('page:', m.text()); });
page.on('pageerror', e => console.error('page error:', e.message));
await page.goto(`http://localhost:${port}/viewer.html`);
await page.waitForFunction(() => window.sceneReady === true, null, { timeout: 120000 });
for (const view of views) {
  await page.evaluate(v => window.renderView(v), view);
  const out = path.join(outDir, `${view.name}.png`);
  await page.screenshot({ path: out });
  console.log('saved', out);
}
await browser.close();
server.close();
