// SSH-side renderer. Input JSON only; no secrets or untrusted shell commands.
const fs = require('node:fs');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const root = process.cwd();
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const jobs = manifest.jobs;
const workers = Math.max(1, Math.min(4, Math.floor(manifest.workers || 1)));
if (!Array.isArray(jobs) || !jobs.length) throw new Error('No render jobs');
fs.mkdirSync(path.join(root, 'clips'), {recursive: true});
fs.mkdirSync(path.join(root, 'props'), {recursive: true});
const browser = manifest.browser_executable || '/usr/bin/chromium';
if (!path.isAbsolute(browser)) throw new Error('Browser path must be absolute');
const glFlags = manifest.gl ? ['--gl',manifest.gl] : [];
const chromeFlags = manifest.chrome_mode ? ['--chrome-mode',manifest.chrome_mode] : [];
if (manifest.require_hardware_webgl) {
  const diagnostic = spawnSync(path.join(root,'node_modules/.bin/remotion'),
    ['gpu','--browser-executable',browser,...glFlags,...chromeFlags],
    {cwd:root,encoding:'utf8',timeout:120000});
  if (diagnostic.error || diagnostic.status !== 0 ||
      !/WebGL:\s*Hardware accelerated/i.test(diagnostic.stdout || '')) {
    throw new Error('Vast GPU WebGL check failed; declining to render on billed software ' +
      'SwiftShader. GPU report: ' + String(diagnostic.stdout || diagnostic.stderr).slice(-1300));
  }
}
const results = {};
const statusPath = path.join(root, 'status.json');
const save = () => { fs.writeFileSync(statusPath + '.tmp', JSON.stringify(results, null, 2)); fs.renameSync(statusPath + '.tmp', statusPath); };
let next = 0;
async function render(job) {
  if (!/^s[0-9]{2,4}$/.test(job.id)) throw new Error('Invalid scene id');
  const props = path.join(root, 'props', job.id + '.json');
  const clip = path.join(root, 'clips', job.id + '.mp4');
  const temp = path.join(root, 'clips', job.id + '.partial.mp4');
  fs.writeFileSync(props, JSON.stringify(job.props));
  const args = ['render','src/index.ts','Scene',temp,'--props',props,
                '--browser-executable',browser, '--codec','h264',
                '--crf', String(job.crf), '--concurrency','1', '--log','error',...glFlags,...chromeFlags];
  if (fs.existsSync(temp)) fs.unlinkSync(temp);
  const message = await new Promise((resolve) => {
    const child = spawn(path.join(root,'node_modules/.bin/remotion'), args, {cwd:root});
    let error = '';
    child.stderr.on('data', (chunk) => { error = (error + String(chunk)).slice(-3000); });
    child.on('error', (e) => resolve(String(e)));
    child.on('close', (code) => resolve(code === 0 ? '' : error || `renderer exited ${code}`));
  });
  if (message || !fs.existsSync(temp) || fs.statSync(temp).size === 0) {
    if (fs.existsSync(temp)) fs.unlinkSync(temp);
    throw new Error(message || 'empty output clip');
  }
  fs.renameSync(temp, clip);
  return fs.statSync(clip).size;
}
async function run() {
  await Promise.all(Array.from({length: Math.min(workers, jobs.length)}, async () => {
    while (next < jobs.length) {
      const job = jobs[next++];
      try { results[job.id] = {ok:true, bytes:await render(job)}; console.log(`RENDER_OK ${job.id}`); }
      catch(e) { results[job.id] = {ok:false, error:String(e).slice(-1000)}; console.error(`RENDER_FAIL ${job.id}: ${e}`); }
      save();
    }
  }));
  if (Object.values(results).some(x => !x.ok)) process.exitCode = 1;
}
run().catch((e) => { console.error(e); process.exitCode = 1; });
