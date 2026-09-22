/* ==========================================================================
   AutoVideoBot Web UI - the logic
   --------------------------------------------------------------------------
   Plain JavaScript, no frameworks and no build step, so it runs from a fresh
   clone with nothing installed but Python.

   The only slightly clever part is the live log: an EventSource (Server-Sent
   Events) connection streams each line of the build the moment the bot prints
   it, which is what makes the page feel like a terminal.
   ========================================================================== */

const $  = (id) => document.getElementById(id);
const $$ = (sel) => document.querySelectorAll(sel);

let STATE = null;          // last /api/state payload
let CURRENT_JOB = null;    // the job we are watching
let EVENT_SOURCE = null;
let MODE = 'script';       // script | topic
let CONFIG_VALUES = {};    // snapshot from /api/config

/* ------------------------------------------------------------------ utils */
function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = message;
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 320);
  }, kind === 'bad' ? 9000 : 5200);
}

function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function api(path, options) {
  const res = await fetch(path, Object.assign({
    headers: { 'Content-Type': 'application/json' },
  }, options || {}));
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* keep */ }
    throw new Error(detail);
  }
  const text = await res.text();
  try { return JSON.parse(text); } catch (e) { return text; }
}

/* ------------------------------------------------------------- navigation */
const VIEW_INFO = {
  dashboard: ['Dashboard', 'Check that everything is ready, then make a video.'],
  create:    ['Create a video', 'Paste a script or describe a topic. The log on the right is live.'],
  library:   ['My videos', 'Play a finished video, redo one stage, or clean up disk space.'],
  providers: ['Providers', 'Swap any tool for another. Nothing else in the bot changes.'],
  settings:  ['Settings & keys', 'API keys, common options, your own music and logo.'],
  help:      ['Help', 'Everything explained, including the script format and a cost table.'],
};

function go(view) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
  $$('#nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  const [title, sub] = VIEW_INFO[view] || ['AutoVideoBot', ''];
  $('viewTitle').textContent = title;
  $('viewSub').textContent = sub;
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (view === 'library') loadProjects();
  if (view === 'providers') loadProviders();
  if (view === 'settings') { loadEnv(); loadConfig(); }
}

$$('#nav button').forEach(btn => btn.addEventListener('click', () => go(btn.dataset.view)));

/* ============================================================ STATE LOAD */
async function loadState() {
  try {
    STATE = await api('/api/state');
  } catch (e) {
    $('sideStatus').innerHTML = '<span style="color:var(--bad)">server not reachable</span>';
    return;
  }
  $('resolutionPill').textContent = STATE.resolution[0] + 'x' + STATE.resolution[1]
    + ' @ ' + STATE.fps + 'fps';
  $('sideStatus').innerHTML =
    'python ' + esc(STATE.python) + '<br>' +
    STATE.projects.length + ' project(s)<br>' +
    '<code>' + esc(STATE.root.split(/[\\/]/).pop()) + '</code>';

  renderDashboard();
  fillProviderPickers();
  renderMusicPicker();
}

function activeRow(label, value, pillClass) {
  return `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--line)">
      <span style="color:var(--muted);font-size:13px">${esc(label)}</span>
      <span class="pill ${pillClass || ''}">${esc(value || 'not set')}</span>
    </div>`;
}

function renderDashboard() {
  const a = STATE.active;
  const musicCount = STATE.music.length;

  // ---- cards
  const anyVideo = STATE.projects.some(p => p.has_video);
  const keysSet = STATE.env_keys.filter(k => k.set).length;

  $('dashCards').innerHTML = `
    <div class="card tight">
      <div style="color:var(--muted);font-size:12px">Projects</div>
      <div style="font-size:26px;font-weight:700">${STATE.projects.length}</div>
      <div class="hint" style="margin:0">${STATE.projects.filter(p => p.has_video).length} finished</div>
    </div>
    <div class="card tight">
      <div style="color:var(--muted);font-size:12px">Images</div>
      <div style="font-size:26px;font-weight:700">${esc(a.image)}</div>
      <div class="hint" style="margin:0">${a.image === 'pollinations' ? 'free, no account' : 'configured'}</div>
    </div>
    <div class="card tight">
      <div style="color:var(--muted);font-size:12px">Voice</div>
      <div style="font-size:26px;font-weight:700">${esc(a.tts)}</div>
      <div class="hint" style="margin:0">${a.tts === 'edge' ? 'free, no account' : 'configured'}</div>
    </div>
    <div class="card tight">
      <div style="color:var(--muted);font-size:12px">Keys filled in</div>
      <div style="font-size:26px;font-weight:700">${keysSet}<span style="color:var(--muted);font-size:15px">/${STATE.env_keys.length}</span></div>
      <div class="hint" style="margin:0">${keysSet ? 'ready for paid options' : 'not needed for free mode'}</div>
    </div>`;

  // ---- banner: first-run guidance
  let banner = '';
  if (!STATE.projects.length) {
    banner = `<div class="banner"><span>&#9888;</span><div>
        <b>First time here.</b> The quickest way to know everything works is the
        8-second self-test &mdash; it needs no accounts and takes about a minute.
        <div class="btn-row" style="margin-top:9px">
          <button class="btn primary" onclick="runSelfTest()">Run the self-test</button>
          <button class="btn" onclick="go('help')">Read the 5-minute guide</button>
        </div></div></div>`;
  } else if (!anyVideo) {
    banner = `<div class="banner warn"><span>&#9432;</span><div>
        You have a project but no finished video yet. Open
        <b>My videos</b> to continue it, or start a new one.</div></div>`;
  }
  $('dashBanner').innerHTML = banner;

  // ---- active providers
  $('activeProviders').innerHTML =
    activeRow('Script (LLM)', a.llm, a.llm === 'manual' ? '' : 'act') +
    activeRow('Voice (TTS)', a.tts, a.tts === 'edge' ? 'ok' : 'act') +
    activeRow('Images', a.image, a.image === 'pollinations' ? 'ok' : 'act') +
    activeRow('Renderer', a.assembly, 'ok') +
    `<div class="btn-row" style="margin-top:12px">
       <button class="btn sm" onclick="go('providers')">Change these</button>
     </div>`;

  // ---- music
  $('musicList').innerHTML = musicCount
    ? STATE.music.map(m => `<div class="pill" style="margin:3px 4px 3px 0">&#9835; ${esc(m)}</div>`).join('')
    : `<div class="hint" style="margin:0">No tracks yet &mdash; videos will be narration only,
        which is perfectly fine. Add music in <b>Settings</b>.</div>`;

  renderJobs();
}

function renderJobs() {
  const jobs = STATE ? STATE.jobs : [];
  if (!jobs.length) {
    $('jobsList').innerHTML = '<div class="empty">No builds yet in this session.</div>';
    return;
  }
  // The list is filled by the live job poll below (jobsById holds the details)
  $('jobsList').innerHTML = jobs.map(id => {
    const j = JOBS_BY_ID[id];
    if (!j) return '';
    return jobCard(j);
  }).join('') || '<div class="empty">No builds yet in this session.</div>';
}

const JOBS_BY_ID = {};

function jobCard(j) {
  const status = {
    running: '<span class="pill act"><span class="dotline"></span> running</span>',
    done: '<span class="pill ok">done</span>',
    failed: '<span class="pill bad">failed</span>',
    stopped: '<span class="pill warn">stopped</span>',
  }[j.status] || '';
  return `<div style="padding:9px 0;border-bottom:1px solid var(--line)">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
        <div style="font-size:13px">${esc(j.label)}</div>
        <div>${status}<span class="hint" style="margin-left:8px">${j.seconds}s</span></div>
      </div>
      ${j.status === 'failed' ? `<div class="hint" style="color:var(--bad);margin:4px 0 0">${esc(j.error)}</div>` : ''}
      ${j.result && j.result.video ? `<div class="hint" style="margin:4px 0 0">output:
        <code>${esc(j.result.video)}</code> (${j.result.mb} MB)</div>` : ''}
    </div>`;
}

async function refreshJobs() {
  try {
    const jobs = await api('/api/jobs');
    jobs.forEach(j => { JOBS_BY_ID[j.id] = j; });
    renderJobs();
  } catch (e) { /* ignore */ }
}

/* ============================================================ CREATE TAB */
function setMode(mode) {
  MODE = mode;
  $('scriptPane').style.display = mode === 'script' ? '' : 'none';
  $('topicPane').style.display = mode === 'topic' ? '' : 'none';
  $('modeScript').classList.toggle('primary', mode === 'script');
  $('modeTopic').classList.toggle('primary', mode === 'topic');
}

function fillProviderPickers() {
  if (!STATE) return;
  const P = STATE.providers;
  const fill = (id, list, current) => {
    const sel = $(id);
    const saved = sel.value;
    sel.innerHTML = '<option value="">use my settings</option>' +
      list.map(p => `<option value="${esc(p.name)}">${esc(p.name)}${p.cost ? ' &mdash; ' + esc(p.cost) : ''}</option>`).join('');
    sel.value = saved;
  };
  fill('pickTts', P.tts || [], STATE.active.tts);
  fill('pickImage', P.image || [], STATE.active.image);
  fill('pickLlm', P.llm || [], STATE.active.llm);
}

function renderMusicPicker() {
  if (!STATE) return;
  const sel = $('pickMusic');
  sel.innerHTML = '<option value="">automatic (config setting)</option>' +
    STATE.music.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
}

async function refreshVoices() {
  const provider = $('pickTts').value;
  const sel = $('pickVoice');
  sel.innerHTML = '<option value="">loading voices...</option>';
  try {
    const data = await api('/api/voices' + (provider ? '?provider=' + encodeURIComponent(provider) : ''));
    const list = data.voices || [];
    sel.innerHTML = '<option value="">use my settings</option>' +
      list.map(v => `<option value="${esc(String(v).split(/\s+/)[0])}">${esc(v)}</option>`).join('');
    if (data.error) sel.innerHTML = `<option value="">(${esc(data.error).slice(0, 90)})</option>`;
  } catch (e) {
    sel.innerHTML = '<option value="">could not list voices</option>';
  }
}

async function loadExampleScript() {
  try {
    const text = await api('/api/example-script');
    $('scriptText').value = text;
    toast('Example script loaded &mdash; 4 scenes, 47 seconds.');
  } catch (e) {
    toast('Could not load the example: ' + esc(e.message), 'bad');
  }
}

async function loadExampleThenCreate() {
  go('create');
  await loadExampleScript();
}

function loadScriptFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    $('scriptText').value = reader.result;
    $('runName').value = file.name.replace(/\.[^.]+$/, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'my-video';
    toast('Loaded ' + esc(file.name));
  };
  reader.readAsText(file);
}

/* --------------------------------------------------------------- building */
async function startBuild() {
  const name = ($('runName').value || '').trim();
  if (!name) { toast('Give the video a name first.', 'bad'); return; }

  const overrides = {};
  const music = $('pickMusic').value;
  if (music) overrides['audio.music.mode'] = 'filename';
  if (music) overrides['audio.music.filename'] = music;

  const payload = {
    name: name,
    mode: MODE,
    script_text: MODE === 'script' ? $('scriptText').value : '',
    topic: MODE === 'topic' ? $('topicText').value : '',
    duration: MODE === 'topic' ? Number($('topicDuration').value || 120) : null,
    instructions: MODE === 'topic' ? $('topicInstructions').value : '',
    quality: $('quality').value,
    aspect: $('aspect').value,
    fps: $('fps').value,
    force: $('forceRebuild').checked,
    tts: $('pickTts').value,
    image: $('pickImage').value,
    llm: $('pickLlm').value,
    voice: $('pickVoice').value,
    overrides: overrides,
  };

  try {
    const res = await api('/api/run', { method: 'POST', body: JSON.stringify(payload) });
    watchJob(res.job, 'Building "' + name + '"');
    toast('Build started. You can leave this page &mdash; the bot keeps working.', 'ok');
  } catch (e) {
    toast('Could not start: ' + esc(e.message), 'bad');
  }
}

/* ---------------------------------------------------------------- watcher */
function watchJob(jobId, label) {
  CURRENT_JOB = jobId;
  $('buildLog').innerHTML = '';
  $('buildBar').style.display = '';
  $('buildBtn').disabled = true;
  $('stopBtn').disabled = false;
  $('resultCard').style.display = 'none';
  $('buildTitle').textContent = label || 'Build monitor';

  if (EVENT_SOURCE) { EVENT_SOURCE.close(); EVENT_SOURCE = null; }

  const es = new EventSource('/api/job/' + jobId + '/stream');
  EVENT_SOURCE = es;

  es.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch (e) { return; }
    if (data.line !== undefined) appendLog(data.line);
    if (data.meta) {
      const p = data.meta.progress || {};
      $('buildBar').querySelector('i').style.width = (p.percent || 0) + '%';
      if (data.meta.status !== 'running') {
        finishJob(jobId, data.meta);
      }
    }
  };
  es.addEventListener('end', () => { es.close(); EVENT_SOURCE = null; });
  es.onerror = () => { es.close(); EVENT_SOURCE = null; };
}

function logClass(line) {
  const s = line.trim();
  if (/^===+\s*STAGE|STAGE \d+\s*\/\s*\d+/.test(s)) return 'l-stage';
  if (/^(✔|ok\b|OK\b)/.test(s)) return 'l-ok';
  if (/^(⚠|!)/.test(s)) return 'l-warn';
  if (/^(✖|x\b|FAILED|Traceback)/i.test(s)) return 'l-fail';
  if (/^CMD /.test(s)) return 'l-cmd';
  if (/^·/.test(s)) return 'l-info';
  return '';
}

function appendLog(line) {
  const box = $('buildLog');
  const div = document.createElement('div');
  div.className = logClass(line);
  div.textContent = line;
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.appendChild(div);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function finishJob(jobId, meta) {
  $('buildBtn').disabled = false;
  $('stopBtn').disabled = true;
  if (EVENT_SOURCE) { EVENT_SOURCE.close(); EVENT_SOURCE = null; }

  const snap = await api('/api/job/' + jobId);
  JOBS_BY_ID[jobId] = snap;

  const bar = $('buildBar').querySelector('i');
  bar.style.width = (meta.status === 'done' ? 100 : meta.progress.percent) + '%';

  const kind = meta.status === 'done' ? 'ok' : (meta.status === 'stopped' ? 'warn' : 'bad');
  appendLog('');
  appendLog(meta.status === 'done' ? '=== FINISHED ==='
    : meta.status === 'stopped' ? '=== STOPPED (finished work is cached) ==='
    : '=== FAILED ===');
  toast(meta.status === 'done' ? 'Build finished.' :
        (meta.status === 'stopped' ? 'Stopped. Press Build again to continue.' : 'Build failed &mdash; see the log.'),
        kind);

  if (snap.result && snap.result.video) {
    showResult(snap.result);
  } else if (LAST_JOB_KIND === 'test' && meta.status === 'failed') {
    const blob = (snap.lines || []).join(' ').toLowerCase();
    const networky = ['network problem', 'unavailable', 'cannot connect',
                      'max retries', 'ssl', 'unreachable', 'timed out']
      .some(w => blob.includes(w));
    if (networky) offerOfflineSelfTest();
  }
  LAST_JOB_KIND = '';
  loadState();
  if (document.querySelector('#view-library.active')) loadProjects();
}

function showResult(result) {
  $('resultCard').style.display = '';
  $('resultBody').innerHTML = `
    <video class="player" controls src="/api/media/${encodeURIComponent(result.slug || '')}/video"></video>
    <div class="btn-row" style="margin-top:12px">
      <a class="btn primary" href="/api/download/${encodeURIComponent(result.slug || '')}/video" download>Download MP4</a>
      <a class="btn" href="/api/download/${encodeURIComponent(result.slug || '')}/thumbnail" download>Thumbnail</a>
      <a class="btn" href="/api/download/${encodeURIComponent(result.slug || '')}/metadata" download>YouTube metadata</a>
      <a class="btn" href="/api/download/${encodeURIComponent(result.slug || '')}/srt" download>Subtitles (srt)</a>
      <button class="btn" onclick="go('library')">Open in My videos</button>
    </div>
    <div class="hint" style="margin-top:10px">${result.mb ? result.mb + ' MB &middot; ' : ''}${esc(result.video || '')}</div>`;
}

async function stopJob() {
  if (!CURRENT_JOB) return;
  try {
    await api('/api/job/' + CURRENT_JOB + '/stop', { method: 'POST' });
    toast('Stop requested &mdash; the bot will stop at the end of this stage.', 'warn');
  } catch (e) { toast('Could not stop: ' + esc(e.message), 'bad'); }
}

/* ------------------------------------------------------------------ misc */
async function runSelfTest(offline) {
  go('dashboard');
  const body = offline ? { tts: 'test', force: true } : {};
  try {
    const res = await api('/api/test', { method: 'POST', body: JSON.stringify(body) });
    $('testBar').style.display = '';
    toast(offline
      ? 'Offline self-test started: uses the built-in tone voice, needs no internet.'
      : 'Self-test started (about a minute). Watch the build monitor.', 'ok');
    go('create');
    watchJob(res.job, offline ? 'Offline self-test (no internet needed)'
                              : 'Self-test: tiny 8-second video');
    LAST_JOB_KIND = 'test';
  } catch (e) {
    toast('Could not start the self-test: ' + esc(e.message), 'bad');
  }
}

let LAST_JOB_KIND = '';
let LAST_JOB_OFFLINE_HINT = false;

/*
  The self-test answers two different questions, and it is important not to
  confuse them:

    "is my installation correct?"   -> the normal self-test (uses your voice
                                       provider; the free one is a web service)
    "does the machine work at all?" -> the offline self-test (built-in tone)

  So when the normal one fails because of the network, we say exactly that and
  offer the offline run rather than letting someone think their setup is broken.
*/
function offerOfflineSelfTest() {
  const card = $('resultCard');
  card.style.display = '';
  $('resultBody').innerHTML = `
    <div class="banner warn" style="margin-bottom:12px">
      <span>&#9432;</span>
      <div>The self-test reached the voice stage and the free voice service was
        unreachable. That is a <b>network</b> result, not a broken installation.
        You can prove the rest of the toolchain right now with the offline test -
        it needs no internet at all and produces a real video.</div>
    </div>
    <div class="btn-row">
      <button class="btn primary" onclick="runSelfTest(true)">Run the offline self-test</button>
      <button class="btn" onclick="go('providers')">Test my providers instead</button>
      <button class="btn" onclick="go('help')">Read the troubleshooting</button>
    </div>`;
}

async function runDoctor() {
  try {
    const res = await api('/api/doctor', { method: 'POST', body: JSON.stringify({}) });
    go('create');
    watchJob(res.job, 'Health check');
    toast('Running the health check...');
  } catch (e) {
    toast('Could not run the health check: ' + esc(e.message), 'bad');
  }
}

/* =============================================================== LIBRARY */
async function loadProjects() {
  try {
    const projects = await api('/api/projects');
    if (!projects.length) {
      $('projectList').innerHTML = '<div class="empty">No videos yet. Go to <b>Create a video</b>.</div>';
      $('projectDetail').innerHTML = '';
      return;
    }
    $('projectList').innerHTML = projects.map(p => `
      <div class="proj">
        <div class="thumb" ${p.has_video ? `style="background-image:url('/api/media/${encodeURIComponent(p.slug)}/thumbnail')"` : ''}>
          ${p.has_video ? '' : 'no video yet'}
        </div>
        <div class="meta">
          <h3>${esc(p.title)}</h3>
          <div class="row">
            <span class="pill">${esc(p.slug)}</span>
            <span>${p.scenes} scene(s)</span>
            <span>${p.size_mb} MB</span>
            ${p.has_video ? '<span class="pill ok">finished</span>' : '<span class="pill warn">incomplete</span>'}
          </div>
        </div>
        <div class="actions">
          ${p.has_video ? `<button class="btn sm" onclick="playProject('${esc(p.slug)}')">&#9654; Play</button>` : ''}
          <button class="btn sm" onclick="openProject('${esc(p.slug)}')">Details</button>
          <a class="btn sm" href="/api/download/${encodeURIComponent(p.slug)}/video" download>MP4</a>
        </div>
      </div>`).join('');
  } catch (e) {
    $('projectList').innerHTML = '<div class="empty">Could not list projects: ' + esc(e.message) + '</div>';
  }
}

function playProject(slug) {
  $('projectDetail').innerHTML = `
    <div class="card">
      <h2>${esc(slug)}</h2>
      <video class="player" controls src="/api/media/${encodeURIComponent(slug)}/video"></video>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn" onclick="openProject('${esc(slug)}')">Show details</button>
        <a class="btn" href="/api/download/${encodeURIComponent(slug)}/video" download>Download</a>
      </div>
    </div>`;
  $('projectDetail').scrollIntoView({ behavior: 'smooth' });
}

const STAGE_LABELS = {
  script: '1. Script', voice: '2. Voiceover', timing: '3. Timing',
  images: '4. Images', motion: '5. Motion', transition: '6. Join clips',
  subtitles: '7. Captions', mix: '8. Audio mix', assembly: '9. Final render',
  extras: '10. Thumbnail &amp; metadata',
};

async function openProject(slug) {
  let p;
  try {
    p = await api('/api/project/' + encodeURIComponent(slug));
  } catch (e) {
    toast('Could not open: ' + esc(e.message), 'bad');
    return;
  }

  const stages = Object.entries(p.stages).map(([key, done]) =>
    `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)">
       <span style="font-size:13px">${STAGE_LABELS[key] || key}</span>
       <span>${done ? '<span class="pill ok">done</span>' : '<span class="pill">not yet</span>'}
         <button class="btn sm" style="margin-left:6px"
           onclick="rerunStage('${esc(slug)}','${key}')">Run</button>
         <button class="btn sm" onclick="rerunStage('${esc(slug)}','${key}',true)">Force</button>
       </span>
     </div>`).join('');

  const scenes = p.scenes.map(s => `
    <tr>
      <td class="mono">${esc(s.id)}</td>
      <td>${s.start != null ? Number(s.start).toFixed(1) + 's' : '-'}</td>
      <td>${s.duration != null ? Number(s.duration).toFixed(1) + 's' : '-'}</td>
      <td>${s.words || ''}</td>
      <td>${esc(s.motion || '')}${s.tempo && Math.abs(s.tempo - 1) > 0.01 ? ` <span class="pill warn">${Number(s.tempo).toFixed(2)}&times;</span>` : ''}</td>
      <td>${s.has_image ? '&#10003;' : '&mdash;'}</td>
      <td>${s.has_clip ? '&#10003;' : '&mdash;'}</td>
      <td style="max-width:340px">${esc((s.narration || '').slice(0, 90))}</td>
    </tr>`).join('');

  const meta = p.metadata && p.metadata.title ? `
    <div class="card">
      <h2>YouTube metadata (ready to paste)</h2>
      <label class="field"><span>Title</span>
        <input type="text" readonly value="${esc(p.metadata.title || '')}"></label>
      <label class="field"><span>Description</span>
        <textarea readonly style="min-height:130px">${esc(p.metadata.description || '')}</textarea></label>
      <label class="field"><span>Tags</span>
        <input type="text" readonly value="${esc((p.metadata.tags || []).join(', '))}"></label>
    </div>` : '';

  $('projectDetail').innerHTML = `
    <div class="card">
      <h2>${esc(p.title)}</h2>
      <p class="hint">${esc(p.slug)} &mdash; ${p.scenes.length} scene(s)
        ${p.outputs.video ? '&middot; ' + p.outputs.video_mb + ' MB final video' : ''}</p>
      <div class="btn-row">
        ${p.outputs.video ? `<a class="btn primary" href="/api/download/${encodeURIComponent(slug)}/video" download>Download MP4</a>` : ''}
        ${p.outputs.thumbnail ? `<a class="btn" href="/api/download/${encodeURIComponent(slug)}/thumbnail" download>Thumbnail</a>` : ''}
        ${p.outputs.metadata ? `<a class="btn" href="/api/download/${encodeURIComponent(slug)}/metadata" download>Metadata</a>` : ''}
        ${p.outputs.srt ? `<a class="btn" href="/api/download/${encodeURIComponent(slug)}/srt" download>Captions</a>` : ''}
        <button class="btn" onclick="openFolder('${esc(slug)}')">Open folder</button>
        <button class="btn" onclick="cleanProject('${esc(slug)}',false)">Clean cache</button>
        <button class="btn danger" onclick="deleteProject('${esc(slug)}')">Delete project</button>
      </div>
      ${p.outputs.video ? `<video class="player" style="margin-top:14px" controls
          src="/api/media/${encodeURIComponent(slug)}/video"></video>` : ''}
    </div>

    <div class="split">
      <div>
        <div class="card">
          <h2>Scenes</h2>
          <div class="scroll-x">
            <table>
              <thead><tr><th>id</th><th>start</th><th>len</th><th>words</th><th>motion</th>
                <th>img</th><th>clip</th><th>narration</th></tr></thead>
              <tbody>${scenes || '<tr><td colspan="8" class="empty">no scenes yet</td></tr>'}</tbody>
            </table>
          </div>
        </div>
        ${meta}
      </div>
      <div>
        <div class="card">
          <h2>Stages</h2>
          <p class="hint">Re-run one step without touching the rest. <b>Force</b> ignores the cache.</p>
          ${stages}
        </div>
        <div class="card">
          <h2>Files</h2>
          <div class="scroll-x">
            <table><tbody>
              ${p.files.map(f => `<tr>
                <td>${esc(f.label)}</td>
                <td class="mono">${esc(f.name)}</td>
                <td>${f.mb} MB</td>
              </tr>`).join('') || '<tr><td class="empty">nothing yet</td></tr>'}
            </tbody></table>
          </div>
        </div>
        ${p.runs && p.runs.length ? `<div class="card">
          <h2>Run history</h2>
          <table><tbody>${p.runs.map(r => `<tr><td class="mono">${esc(r.at)}</td>
            <td>${esc(r.command)}</td><td>${r.seconds}s</td></tr>`).join('')}</tbody></table>
        </div>` : ''}
      </div>
    </div>`;
  $('projectDetail').scrollIntoView({ behavior: 'smooth' });
}

async function rerunStage(slug, stage, force) {
  try {
    const res = await api('/api/stage', {
      method: 'POST',
      body: JSON.stringify({ slug, stage, force: !!force }),
    });
    toast('Re-running ' + stage + (force ? ' (forced)' : '') + '...');
    go('create');
    watchJob(res.job, 'Stage ' + stage + ' -> ' + slug);
  } catch (e) {
    toast('Could not start that stage: ' + esc(e.message), 'bad');
  }
}

async function cleanProject(slug, all) {
  if (!confirm('Delete the intermediate files of "' + slug + '"?\n\n' +
               'The final video, audio, script and captions are kept. New renders will just take longer.')) return;
  try {
    const res = await api('/api/clean', { method: 'POST', body: JSON.stringify({ slug, all }) });
    go('create');
    watchJob(res.job, 'Cleaning ' + slug);
  } catch (e) {
    toast('Could not clean: ' + esc(e.message), 'bad');
  }
}

async function deleteProject(slug) {
  if (!confirm('DELETE "' + slug + '" completely?\n\nThis removes the video and everything that made it. There is no undo.')) return;
  if (!confirm('Really delete "' + slug + '"? Last chance.')) return;
  try {
    await api('/api/delete-project', { method: 'POST', body: JSON.stringify({ slug }) });
    toast('Deleted ' + esc(slug), 'ok');
    loadProjects();
    $('projectDetail').innerHTML = '';
    loadState();
  } catch (e) {
    toast('Could not delete: ' + esc(e.message), 'bad');
  }
}

async function openFolder(slug) {
  try {
    const res = await api('/api/open-folder', { method: 'POST', body: JSON.stringify({ slug, sub: 'output' }) });
    toast(res.ok ? 'Opened: ' + esc(res.path) : esc(res.message), res.ok ? 'ok' : 'warn');
  } catch (e) {
    toast('Could not open the folder: ' + esc(e.message), 'bad');
  }
}

/* ============================================================= PROVIDERS */
const KIND_LABELS = { llm: 'Script writer (LLM)', tts: 'Voice (TTS)', image: 'Images', assembly: 'Renderer' };

async function loadProviders() {
  let data;
  try { data = await api('/api/providers'); }
  catch (e) { toast('Could not load providers', 'bad'); return; }

  const html = Object.entries(data.providers).map(([kind, list]) => `
    <div class="card">
      <h2>${esc(KIND_LABELS[kind] || kind)}</h2>
      <p class="hint">Set one as active in <b>Settings &rarr; Advanced</b>:
        <code>${kind === 'assembly' ? 'motion.engine' : kind + '.provider'}</code></p>
      <div class="scroll-x">
        <table>
          <thead><tr><th>Provider</th><th>Cost</th><th>Quality</th><th>Setup</th><th>Key</th><th></th></tr></thead>
          <tbody>
            ${list.map(p => `
              <tr id="prow-${kind}-${esc(p.name)}">
                <td><b>${esc(p.name)}</b>${data.active[kind] === p.name ? ' <span class="pill act">active</span>' : ''}
                    <div class="hint" style="margin:2px 0 0">${esc(p.doc || '')}</div></td>
                <td>${esc(p.cost || '')}</td>
                <td>${esc(p.quality || '')}</td>
                <td>${esc(p.setup_time || '')}</td>
                <td>${p.needs_key ? '<span class="pill warn">yes</span>' : '<span class="pill ok">no</span>'}</td>
                <td><div class="btn-row">
                  <button class="btn sm" onclick="checkProvider('${kind}','${esc(p.name)}')">Test</button>
                  <button class="btn sm" onclick="activateProvider('${kind}','${esc(p.name)}')">Use</button>
                </div></td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`).join('');

  $('providerList').innerHTML = html;
}

async function checkProvider(kind, name) {
  const row = $('prow-' + kind + '-' + name);
  const cell = row.querySelector('td:last-child .btn-row');
  const original = cell.innerHTML;
  cell.innerHTML = '<span class="spin"></span> testing...';
  try {
    const res = await api('/api/provider/check', {
      method: 'POST', body: JSON.stringify({ kind, name }),
    });
    cell.innerHTML = original;
    toast('<b>' + esc(name) + '</b>: ' + esc(res.message).replace(/\n/g, '<br>'),
          res.ok ? 'ok' : 'warn');
  } catch (e) {
    cell.innerHTML = original;
    toast('Test failed: ' + esc(e.message), 'bad');
  }
}

async function activateProvider(kind, name) {
  const key = kind === 'assembly' ? 'motion.engine' : kind + '.provider';
  try {
    const res = await api('/api/config', { method: 'POST', body: JSON.stringify({ values: { [key]: name } }) });
    if (res.changed && res.changed.length) {
      toast('<b>' + esc(key) + '</b> is now <b>' + esc(name) + '</b>', 'ok');
      loadProviders(); loadState();
    } else {
      toast('Could not find ' + key + ' in config.yaml', 'warn');
    }
  } catch (e) {
    toast('Could not switch: ' + esc(e.message), 'bad');
  }
}

/* ============================================================== SETTINGS */
async function loadEnv() {
  let data;
  try { data = await api('/api/env'); } catch (e) { return; }
  const filled = data.keys.filter(k => k.set).length;
  $('envPill').textContent = filled + ' of ' + data.keys.length + ' filled in';
  $('envPill').className = 'pill ' + (filled ? 'ok' : '');
  $('envFields').innerHTML = data.keys.map(k => `
    <label class="field">
      <span>${esc(k.label)} ${k.set ? '<span class="pill ok">set</span>' : '<span class="pill">empty</span>'}</span>
      <input type="password" data-envkey="${esc(k.key)}"
             placeholder="${k.set ? 'saved - type a new value to replace it' : 'paste here'}"
             autocomplete="off">
    </label>`).join('');
}

async function saveEnv() {
  const values = {};
  $$('#envFields input').forEach(inp => {
    if (inp.value.trim()) values[inp.dataset.envkey] = inp.value.trim();
  });
  if (!Object.keys(values).length) { toast('Nothing new to save.', 'warn'); return; }
  try {
    const res = await api('/api/env', { method: 'POST', body: JSON.stringify({ values }) });
    toast('Saved: ' + esc(res.saved.join(', ')), 'ok');
    loadEnv();
  } catch (e) {
    toast('Could not save: ' + esc(e.message), 'bad');
  }
}

const QUICK_SETTINGS = [
  ['video.crf', 'Quality (lower = better, 18-24)', 'number'],
  ['video.preset', 'Encoder speed (ultrafast ... slow)', 'text'],
  ['video.codec', 'Codec (h264 plays everywhere)', 'text'],
  ['motion.supersample', 'Motion smoothness (2 = low RAM, 6 = best)', 'text'],
  ['motion.zoom_amount', 'Zoom strength (1.12 = 12%)', 'number'],
  ['motion.color_grade', 'Colour grade (cinematic, warm, cool, noir)', 'text'],
  ['transitions.type', 'Transition between scenes', 'text'],
  ['transitions.duration', 'Transition length in seconds', 'number'],
  ['subtitles.enabled', 'Captions on/off', 'bool'],
  ['subtitles.burn_in', 'Burn captions into the video', 'bool'],
  ['subtitles.style.font_size', 'Caption size (1080p)', 'number'],
  ['audio.music.enabled', 'Background music on/off', 'bool'],
  ['audio.music.volume_db', 'Music volume under the voice (dB)', 'number'],
  ['audio.music.ducking', 'Auto-lower music while speaking', 'bool'],
  ['audio.voice.target_loudness_lufs', 'Narration loudness (-16 = YouTube)', 'number'],
  ['image.steps', 'Image detail (steps, 20-40)', 'number'],
  ['image.seed_mode', 'Image seeds: random or fixed', 'text'],
  ['system.parallel_scenes', 'Scenes rendered at once (1 = safest)', 'number'],
  ['system.encode_threads', 'Encoder threads (4 is safe, 0 = auto)', 'number'],
  ['system.on_error', 'On error: continue or abort', 'text'],
];

async function loadConfig() {
  let data;
  try { data = await api('/api/config'); } catch (e) { return; }
  CONFIG_VALUES = data.values;
  renderQuickSettings();
  renderConfigTable();
}

function renderQuickSettings() {
  $('quickSettings').innerHTML = QUICK_SETTINGS.map(([key, label, type]) => {
    const value = CONFIG_VALUES[key];
    if (value === undefined) return '';
    if (type === 'bool') {
      const on = String(value).toLowerCase() === 'true';
      return `<label class="switch" style="margin-bottom:12px">
          <input type="checkbox" data-cfgkey="${esc(key)}" ${on ? 'checked' : ''}>
          <span style="font-size:13px">${esc(label)}</span></label>`;
    }
    return `<label class="field">
        <span>${esc(label)}</span>
        <input type="${type === 'number' ? 'number' : 'text'}" step="any"
               data-cfgkey="${esc(key)}" value="${esc(value)}">
      </label>`;
  }).join('');
}

function renderConfigTable() {
  const filter = ($('cfgFilter') && $('cfgFilter').value || '').toLowerCase();
  const keys = Object.keys(CONFIG_VALUES)
    .filter(k => !filter || k.toLowerCase().includes(filter))
    .sort();
  $('cfgTable').querySelector('tbody').innerHTML = keys.slice(0, 400).map(k => `
    <tr>
      <td class="mono" style="max-width:270px">${esc(k)}</td>
      <td><input type="text" data-cfgkey="${esc(k)}" value="${esc(CONFIG_VALUES[k])}"
                 style="padding:4px 7px;font-size:12px"></td>
    </tr>`).join('') + (keys.length > 400
      ? `<tr><td colspan="2" class="hint">${keys.length - 400} more hidden - narrow the filter</td></tr>` : '');
}

function filterConfig() { renderConfigTable(); }

async function saveQuickSettings() {
  const values = {};
  $$('[data-cfgkey]').forEach(el => {
    if (el.type === 'checkbox') values[el.dataset.cfgkey] = el.checked;
    else if (el.value !== undefined) values[el.dataset.cfgkey] = el.value;
  });
  try {
    const res = await api('/api/config', { method: 'POST', body: JSON.stringify({ values }) });
    toast('Saved ' + res.changed.length + ' setting(s).' +
          (res.not_found.length ? ' Not found: ' + esc(res.not_found.join(', ')) : ''), 'ok');
    loadConfig(); loadState();
  } catch (e) {
    toast('Could not save: ' + esc(e.message), 'bad');
  }
}

async function uploadFile(input, route) {
  const file = input.files && input.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  if (route === 'asset') form.append('kind', input.dataset.kind || 'watermark');
  $('uploadLog').innerHTML = '<span class="spin"></span> uploading ' + esc(file.name) + '...';
  try {
    const res = await fetch('/api/upload/' + route, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'upload failed');
    $('uploadLog').innerHTML = '<span style="color:var(--good)">uploaded</span> ' +
      esc(data.name || data.path) + (data.mb ? ' (' + data.mb + ' MB)' : '');
    toast('Added ' + esc(data.name || data.path), 'ok');
    input.value = '';
    loadState();
  } catch (e) {
    $('uploadLog').innerHTML = '<span style="color:var(--bad)">failed:</span> ' + esc(e.message);
    toast('Upload failed: ' + esc(e.message), 'bad');
  }
}

/* ================================================================== boot */
setMode('script');
loadState();
refreshJobs();
refreshVoices();
setInterval(refreshJobs, 5000);
