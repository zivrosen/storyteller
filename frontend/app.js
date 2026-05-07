const $ = (sel) => document.querySelector(sel);

const els = {
  composer: $('#composer'),
  input: $('#story-input'),
  tellBtn: $('#tell-btn'),
  progress: $('#progress'),
  story: $('#story'),
  storyBody: $('#story-body'),
  readingTime: $('#reading-time'),
  tweak: $('#tweak'),
  tweakInput: $('#tweak-input'),
  tweakBtn: $('#tweak-btn'),
  restartBtn: $('#restart-btn'),
  error: $('#error'),
};

let currentStory = null;

// Maps pipeline event names → which timeline row they affect and how.
// Refinement events fold into the "judge" row but rename it so the user
// understands a polish pass is happening.
const STAGE_MAP = {
  categorize_start: { row: 'categorize', state: 'active' },
  categorize_done:  { row: 'categorize', state: 'done' },
  plan_start:       { row: 'plan', state: 'active' },
  plan_done:        { row: 'plan', state: 'done' },
  tell_start:       { row: 'tell', state: 'active' },
  tell_done:        { row: 'tell', state: 'done' },
  judge_start:      { row: 'judge', state: 'active' },
  judge_done:       { row: 'judge', state: 'done' },
  refine_start:     { row: 'judge', state: 'active', label: 'Polishing the story' },
  refine_done:      { row: 'judge', state: 'done',   label: 'Editor reviewed' },
  tweak_start:      { row: null }, // handled by spinner state on tweak button only
};

function setStage(stage) {
  const cfg = STAGE_MAP[stage];
  if (!cfg || !cfg.row) return;
  const li = document.querySelector(`.timeline li[data-stage="${cfg.row}"]`);
  if (!li) return;
  if (cfg.state === 'active') {
    li.classList.add('active');
    li.classList.remove('done');
  } else if (cfg.state === 'done') {
    li.classList.remove('active');
    li.classList.add('done');
  }
  if (cfg.label) {
    const t = li.querySelector('.text');
    if (t) t.textContent = cfg.label;
  }
}

function resetTimeline() {
  document.querySelectorAll('.timeline li').forEach((li) => {
    li.classList.remove('active', 'done');
  });
  // Restore default labels in case a refinement renamed them.
  const defaults = {
    categorize: 'Reading your request',
    plan: 'Sketching the story arc',
    tell: 'Writing the story',
    judge: 'Asking the editor',
  };
  document.querySelectorAll('.timeline li').forEach((li) => {
    const row = li.dataset.stage;
    const t = li.querySelector('.text');
    if (t && defaults[row]) t.textContent = defaults[row];
  });
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function parseStory(raw) {
  const lines = raw.split('\n').map((l) => l.replace(/\r$/, ''));
  // Strip leading empties
  while (lines.length && !lines[0].trim()) lines.shift();
  let title = '';
  let body = lines;
  if (lines.length) {
    title = lines[0].trim().replace(/^title:\s*/i, '').replace(/^[*_#\s]+|[*_#\s]+$/g, '');
    body = lines.slice(1);
  }
  while (body.length && !body[0].trim()) body.shift();

  // Group remaining lines into paragraphs separated by blank lines.
  const paragraphs = [];
  let current = [];
  for (const line of body) {
    if (line.trim()) {
      current.push(line.trim());
    } else if (current.length) {
      paragraphs.push(current.join(' '));
      current = [];
    }
  }
  if (current.length) paragraphs.push(current.join(' '));
  return { title, paragraphs };
}

function renderStory(text, readingTime) {
  const { title, paragraphs } = parseStory(text);
  const html =
    (title ? `<h2>${escapeHtml(title)}</h2>` : '') +
    paragraphs.map((p) => `<p>${escapeHtml(p)}</p>`).join('');
  els.storyBody.innerHTML = html;
  els.readingTime.textContent = `~${readingTime} read-aloud`;
  els.story.classList.remove('hidden');
  els.story.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function streamSSE(url, body, onMessage) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) {
    let detail = '';
    try { detail = (await resp.text()).slice(0, 200); } catch (_) {}
    throw new Error(`Server returned ${resp.status}${detail ? `: ${detail}` : ''}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buf.indexOf('\n\n')) !== -1) {
      const chunk = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const dataLine = chunk
        .split('\n')
        .find((l) => l.startsWith('data: '));
      if (!dataLine) continue;
      try {
        onMessage(JSON.parse(dataLine.slice(6)));
      } catch (_) {
        /* ignore malformed chunks */
      }
    }
  }
}

function setBusy(busy) {
  els.tellBtn.disabled = busy;
  els.tweakBtn.disabled = busy;
  els.tellBtn.textContent = busy ? 'Telling…' : 'Tell me a story';
  els.tweakBtn.textContent = busy ? 'Polishing…' : 'Apply tweak';
}

function showError(msg) {
  els.error.textContent = msg;
  els.error.classList.remove('hidden');
}

function clearError() {
  els.error.textContent = '';
  els.error.classList.add('hidden');
}

async function generateStory() {
  const input = els.input.value.trim();
  if (!input) return;
  clearError();
  setBusy(true);
  resetTimeline();
  els.story.classList.add('hidden');
  els.tweak.classList.add('hidden');
  els.progress.classList.remove('hidden');

  try {
    await streamSSE('/api/generate', { input }, (msg) => {
      if (msg.type === 'stage') {
        setStage(msg.stage);
      } else if (msg.type === 'story') {
        currentStory = msg.text;
        renderStory(msg.text, msg.reading_time);
        els.tweak.classList.remove('hidden');
      } else if (msg.type === 'error') {
        showError(msg.message);
      }
    });
  } catch (err) {
    showError(err.message || 'Something went wrong.');
  } finally {
    setBusy(false);
    setTimeout(() => els.progress.classList.add('hidden'), 600);
  }
}

async function applyTweak() {
  const request = els.tweakInput.value.trim();
  if (!request || !currentStory) return;
  clearError();
  setBusy(true);
  try {
    await streamSSE(
      '/api/tweak',
      { story: currentStory, request },
      (msg) => {
        if (msg.type === 'story') {
          currentStory = msg.text;
          renderStory(msg.text, msg.reading_time);
          els.tweakInput.value = '';
        } else if (msg.type === 'error') {
          showError(msg.message);
        }
      }
    );
  } catch (err) {
    showError(err.message || 'Something went wrong.');
  } finally {
    setBusy(false);
  }
}

function restart() {
  currentStory = null;
  els.input.value = '';
  els.tweakInput.value = '';
  resetTimeline();
  clearError();
  els.story.classList.add('hidden');
  els.tweak.classList.add('hidden');
  els.progress.classList.add('hidden');
  els.input.focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

els.tellBtn.addEventListener('click', generateStory);
els.tweakBtn.addEventListener('click', applyTweak);
els.restartBtn.addEventListener('click', restart);

els.input.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') generateStory();
});
els.tweakInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') applyTweak();
});
