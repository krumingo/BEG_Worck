/*
 * BEG_WORK control projection — client renderer.
 *
 * The browser does no verification and no interpretation. /api/state has already been
 * verified server-side and sanitised; this file only lays it out. That split is what
 * keeps the GitHub token server-side: there is no build step that could inline it, and
 * the browser never talks to GitHub at all — only to this host's own /api/state.
 *
 * All insertion is via textContent or explicitly constructed elements. Nothing from the
 * payload is ever assigned to innerHTML, so a summary or waiting_for string that happens
 * to contain markup is displayed as text rather than parsed.
 */
'use strict';

const DASH = '—';

/* A glyph per agent state, so the cards do not depend on colour alone. */
const STATE_GLYPH = {
  WORKING: '▶',
  WAITING: '⏸',
  REVIEW: '🔍',
  HANDOFF: '➜',
  PASS: '✓',
  CHANGES_REQUESTED: '↺',
  BLOCKED: '■',
  NOT_ACTIVE: '·',
  UNKNOWN: '?'
};

const STATUS_GLYPH = {
  VALID: '✓',
  STALE: '⏳',
  CONFLICT: '⚠',
  INVALID: '✕',
  UNKNOWN: '…'
};

const el = (id) => document.getElementById(id);

function text(node, value) {
  node.textContent = (value === null || value === undefined || value === '') ? DASH : String(value);
}

function make(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
}

function row(container, rowClass, label, value, mono) {
  const wrap = make('div', rowClass);
  wrap.appendChild(make('dt', null, label));
  const dd = make('dd', mono ? 'mono' : null, (value === null || value === undefined || value === '') ? DASH : value);
  wrap.appendChild(dd);
  container.appendChild(wrap);
  return wrap;
}

function link(url, label) {
  const anchor = make('a', null, label);
  anchor.href = url;
  anchor.target = '_blank';
  /* noreferrer as well as noopener: the target should learn nothing about this host. */
  anchor.rel = 'noopener noreferrer';
  return anchor;
}

function shortSha(sha) {
  return typeof sha === 'string' && sha.length > 8 ? sha.slice(0, 8) : (sha || DASH);
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return '';
  const value = Math.max(0, Math.round(seconds));
  if (value < 60) return `${value}s ago`;
  if (value < 3600) return `${Math.round(value / 60)}m ago`;
  if (value < 86400) return `${Math.round(value / 3600)}h ago`;
  return `${Math.round(value / 86400)}d ago`;
}

function localTime(iso) {
  if (!iso) return null;
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleTimeString([], { hour12: false });
}

/* ---------------- header and status ---------------- */

function renderHeader(data) {
  const header = data.header || {};
  text(el('f-wave'), header.wave);
  text(el('f-flow'), header.flow);
  text(el('f-task'), header.task_id);
  text(el('f-cycle'), header.cycle_label || header.cycle_id);

  const progress = header.progress || {};
  text(el('f-stage'), progress.stage);

  const stateNode = el('f-state');
  text(stateNode, header.state_display);
  stateNode.dataset.state = header.state || 'UNKNOWN';

  const verifiedNode = el('f-verified');
  if (!data.available) {
    verifiedNode.textContent = 'no snapshot has been read yet';
  } else if (data.verified) {
    verifiedNode.textContent = 'verified against the bytes read this round';
  } else {
    verifiedNode.textContent = 'NOT verified this round — treat as unconfirmed';
  }

  const status = data.control_state_status || 'UNKNOWN';
  const statusChip = el('f-status');
  statusChip.dataset.status = status;
  text(el('f-status-value'), status);
  el('f-status-glyph').textContent = STATUS_GLYPH[status] || STATUS_GLYPH.UNKNOWN;

  const linkChip = el('f-link');
  linkChip.dataset.link = data.link || 'OFFLINE';
  text(el('f-link-value'), data.link);

  const verifiedAt = el('f-verified-at');
  text(verifiedAt, localTime(data.last_verified_at) || 'never');
  verifiedAt.title = data.last_verified_at || 'no successful read yet';

  const ageNode = el('f-age');
  if (data.age_seconds === null || data.age_seconds === undefined) {
    ageNode.textContent = '';
  } else {
    ageNode.textContent = data.aged ? `${ago(data.age_seconds)} — AGED` : ago(data.age_seconds);
  }

  text(el('f-next'), data.next_attempt_in === null || data.next_attempt_in === undefined
    ? DASH
    : `${Math.round(data.next_attempt_in)}s`);

  const krum = header.krum_action || {};
  const krumChip = el('f-krum');
  krumChip.dataset.required = krum.required ? 'true' : 'false';
  text(el('f-krum-value'), krum.required ? 'REQUIRED' : 'NONE');

  const reasonNode = el('f-krum-reason');
  if (krum.required && krum.reason) {
    reasonNode.textContent = `KRUM ACTION REQUIRED — ${krum.reason}`;
    reasonNode.hidden = false;
  } else {
    reasonNode.textContent = '';
    reasonNode.hidden = true;
  }

  document.title = header.task_id
    ? `${header.task_id} ${header.state || ''} · BEG_WORK`.trim()
    : 'BEG_WORK Control';
}

/* ---------------- agents ---------------- */

function renderAgents(data) {
  const host = el('f-agents');
  host.textContent = '';
  (data.agents || []).forEach((agent) => {
    const card = make('article', 'agent' + (agent.is_current ? ' agent--current' : ''));
    card.dataset.state = agent.state || 'UNKNOWN';

    const head = make('div', 'agent__head');
    head.appendChild(make('span', 'agent__name', agent.name));
    head.appendChild(make('span', 'agent__role', agent.role));
    if (agent.is_current) head.appendChild(make('span', 'agent__current', 'current'));
    card.appendChild(head);

    const state = make('div', 'agent__state', agent.state || 'UNKNOWN');
    state.dataset.glyph = STATE_GLYPH[agent.state] || STATE_GLYPH.UNKNOWN;
    card.appendChild(state);

    const rows = make('dl', 'agent__rows');
    row(rows, 'agent__row', 'Work-ID', agent.work_id, true);
    row(rows, 'agent__row', 'Waiting for', agent.waiting_for);
    row(rows, 'agent__row', 'Updated', agent.updated_at, true);
    card.appendChild(rows);

    host.appendChild(card);
  });
}

/* ---------------- pipeline ---------------- */

function renderPipeline(data) {
  const host = el('f-pipeline');
  host.textContent = '';
  const activeState = (data.header || {}).state || '';
  (data.pipeline || []).forEach((step) => {
    const item = make('li', 'pipeline__step' + (step.active ? ' pipeline__step--active' : ''));
    if (step.active) item.dataset.state = activeState;
    item.appendChild(make('span', 'pipeline__agent', step.agent));
    item.appendChild(make('span', 'pipeline__name', step.step));
    if (step.badge) item.appendChild(make('span', 'pipeline__badge', step.badge));
    host.appendChild(item);
  });
}

/* ---------------- task and progress ---------------- */

function renderTask(data) {
  const host = el('f-task-kv');
  host.textContent = '';
  const task = data.task;
  if (!task) {
    host.appendChild(make('p', 'empty', 'No task is projected: there is no verified snapshot.'));
    el('f-progress').textContent = '';
    return;
  }
  row(host, 'kv__row', 'Task', task.task_id, true);
  row(host, 'kv__row', 'Cycle', task.cycle_label, true);
  row(host, 'kv__row', 'Current', `${task.current_agent_name || DASH} · ${task.current_role || DASH}`);
  row(host, 'kv__row', 'Current Work-ID', task.current_work_id, true);
  row(host, 'kv__row', 'Pipeline step', task.pipeline_step, true);
  row(host, 'kv__row', 'Next', task.next_agent_name, true);
  row(host, 'kv__row', 'Waiting for', task.waiting_for);
  row(host, 'kv__row', 'Dispatch', task.dispatch_state, true);
  if (task.dispatch_run_url) {
    const wrap = row(host, 'kv__row', 'Dispatch session', '');
    const dd = wrap.querySelector('dd');
    dd.textContent = '';
    dd.className = 'mono';
    dd.appendChild(link(task.dispatch_run_url, task.dispatch_run_url));
  }
  renderProgress(data);
}

function renderProgress(data) {
  const host = el('f-progress');
  host.textContent = '';
  const progress = (data.header || {}).progress || {};
  if (!progress.mode) return;

  /*
   * The stage is always safe to show, but it must carry its own verification status:
   * a stage read from a round that did not verify is a claim, not a fact.
   */
  const verified = progress.stage_verified === true;
  const stageLabel = `${progress.stage || DASH} · ${progress.mode}${verified ? '' : ' · UNVERIFIED'}`;
  const stage = make('span', 'progress__stage', stageLabel);
  if (!verified) stage.classList.add('progress__stage--unverified');
  host.appendChild(stage);

  /*
   * Numbers and the bar are drawn only when the server says they may be. The server
   * withholds them on STAGE_ONLY and on any unverified round, so a state claiming an
   * arithmetically impossible "3 of 8 · 90%" cannot put a 90%-full bar on the wall.
   * The browser never recomputes or infers a figure of its own.
   */
  if (progress.numbers_withheld || progress.percent === null || progress.percent === undefined) {
    host.appendChild(make('p', 'progress__note',
      progress.withheld_reason || 'No proven percentage is published for this task.'));
    return;
  }

  host.appendChild(make('p', 'progress__note',
    `${progress.completed} of ${progress.total} verified milestones · ${progress.percent}%`));
  const bar = make('div', 'progress__bar');
  const fill = make('div', 'progress__fill');
  fill.style.width = `${Math.max(0, Math.min(100, progress.percent))}%`;
  bar.appendChild(fill);
  host.appendChild(bar);
}

/* ---------------- findings ---------------- */

function renderFindings(data) {
  const host = el('f-findings');
  host.textContent = '';
  const findings = data.findings || [];
  if (!findings.length) {
    host.appendChild(make('li', 'empty',
      data.available
        ? 'No findings: the schema, the protocol invariants, the cited blobs, the PR head and the board all agreed this round.'
        : 'No findings yet: nothing has been read.'));
    return;
  }
  findings.forEach((finding) => {
    const item = make('li', 'finding');
    item.dataset.status = finding.status;
    item.appendChild(make('span', 'finding__code', `${finding.status} · ${finding.code}`));
    item.appendChild(document.createTextNode(finding.message));
    host.appendChild(item);
  });
}

/* ---------------- evidence ---------------- */

function evidenceItem(label, valueNodes, matchNode) {
  const item = make('li', 'ev');
  item.appendChild(make('span', 'ev__label', label));
  const value = make('span', 'ev__value');
  valueNodes.forEach((node) => {
    value.appendChild(typeof node === 'string' ? document.createTextNode(node) : node);
  });
  item.appendChild(value);
  if (matchNode) item.appendChild(matchNode);
  return item;
}

function matchLabel(cited, observed) {
  if (!observed) return make('span', 'ev__match ev__match--none', 'not read this round — unverified');
  if (cited && observed.toLowerCase() === String(cited).toLowerCase()) {
    return make('span', 'ev__match ev__match--ok', `re-hashed on the branch: matches ${shortSha(observed)}`);
  }
  return make('span', 'ev__match ev__match--bad', `MISMATCH — branch has ${shortSha(observed)}`);
}

function renderEvidence(data) {
  const host = el('f-evidence');
  host.textContent = '';
  const evidence = data.evidence;
  if (!evidence) {
    host.appendChild(make('li', 'empty', 'No evidence is projected: there is no verified snapshot.'));
    return;
  }

  const active = evidence.active || {};
  host.appendChild(evidenceItem('ACTIVE', [
    active.url ? link(active.url, active.path || 'ACTIVE') : (active.path || DASH),
    ` · cited blob ${shortSha(active.blob_sha)} · source commit ${shortSha(active.source_commit_sha)}`
  ], matchLabel(active.blob_sha, active.observed_blob_sha)));

  if (evidence.review) {
    const review = evidence.review;
    host.appendChild(evidenceItem('INDEPENDENT REVIEW', [
      review.url ? link(review.url, review.path || 'review') : (review.path || DASH),
      ` · verdict ${review.verdict || DASH} on head ${shortSha(review.reviewed_head_sha)} · cited blob ${shortSha(review.blob_sha)}`
    ], matchLabel(review.blob_sha, review.observed_blob_sha)));
  }

  if (evidence.pull_request) {
    const pr = evidence.pull_request;
    const nodes = [
      pr.url ? link(pr.url, `#${pr.number}`) : `#${pr.number}`,
      `${pr.draft ? ' (Draft)' : ''} · cited exact head ${shortSha(pr.cited_head_sha)}`
    ];
    let match;
    if (!pr.observed_head_sha) {
      match = make('span', 'ev__match ev__match--none', 'PR metadata not read this round — exact head unverified');
    } else if (pr.observed_head_sha.toLowerCase() === String(pr.cited_head_sha).toLowerCase()) {
      match = make('span', 'ev__match ev__match--ok',
        `live head matches ${shortSha(pr.observed_head_sha)}${pr.observed_draft ? ' · still Draft' : ' · NOT Draft'}`);
    } else {
      match = make('span', 'ev__match ev__match--bad', `HEAD MOVED — live head is ${shortSha(pr.observed_head_sha)}`);
    }
    host.appendChild(evidenceItem('DRAFT PR', nodes, match));
  }

  if (evidence.handoff) {
    const handoff = evidence.handoff;
    host.appendChild(evidenceItem('HANDOFF', [
      handoff.url ? link(handoff.url, 'comment') : DASH,
      ` · head ${shortSha(handoff.head_sha)} · ${handoff.at || DASH}`
    ], null));
  }

  if (evidence.handoff_comment_sha256) {
    host.appendChild(evidenceItem('HANDOFF SHA-256', [evidence.handoff_comment_sha256], null));
  }

  if ((evidence.canonical_docs || []).length) {
    const item = make('li', 'ev');
    item.appendChild(make('span', 'ev__label', 'CANONICAL DOCS'));
    const value = make('span', 'ev__value');
    evidence.canonical_docs.forEach((doc, index) => {
      if (index) value.appendChild(document.createTextNode(' · '));
      value.appendChild(doc.url ? link(doc.url, doc.path) : document.createTextNode(doc.path || DASH));
      value.appendChild(document.createTextNode(` @ ${shortSha(doc.blob_sha)}`));
    });
    item.appendChild(value);
    host.appendChild(item);
  }

  host.appendChild(evidenceItem('PREVIOUS STATE COMMIT', [
    shortSha(evidence.control_state_commit_sha),
    ` — ${evidence.control_state_note}`
  ], null));
}

/* ---------------- history ---------------- */

function renderHistory(data) {
  const host = el('f-history');
  host.textContent = '';
  const history = data.history || [];
  if (!history.length) {
    host.appendChild(make('li', 'empty', 'No history is projected.'));
    return;
  }
  history.forEach((event) => {
    const item = make('li', 'event');
    item.dataset.kind = event.kind || '';

    const head = make('div', 'event__head');
    head.appendChild(make('span', 'event__when', event.occurred_at));
    head.appendChild(make('span', 'event__kind', event.kind));
    head.appendChild(make('span', 'event__actor', event.actor_name || event.actor));
    if (event.state_after) head.appendChild(make('span', 'event__kind', `→ ${event.state_after}`));
    const cycle = event.cycle_id
      ? `cycle ${event.cycle_id}`
      : (event.mapped_cycle ? `mapped ${event.mapped_cycle}` : '');
    if (cycle) head.appendChild(make('span', 'event__cycle', cycle));
    item.appendChild(head);

    if (event.summary) item.appendChild(make('p', 'event__summary', event.summary));

    const foot = make('div', 'event__foot');
    foot.appendChild(make('span', null, `head ${shortSha(event.head_sha)}`));
    if (event.source_url) foot.appendChild(link(event.source_url, 'evidence'));
    item.appendChild(foot);

    host.appendChild(item);
  });
}

/* ---------------- footer ---------------- */

function renderFooter(data) {
  text(el('f-gate'), data.gate);
  const config = data.config || {};
  text(el('f-repo'), config.repository);
  text(el('f-branch'), config.branch);
  text(el('f-protocol'), (data.header || {}).protocol_version
    ? `protocol v${data.header.protocol_version} · ${(data.header || {}).validation_mode || DASH}`
    : DASH);
  /*
   * Whether a credential is configured is operationally useful; its value is never sent
   * to the browser, so there is nothing here to leak.
   */
  text(el('f-token'), config.token_configured ? 'server-side token: configured' : 'server-side token: none (anonymous reads)');

  const errorNode = el('f-error');
  if (data.last_error) {
    errorNode.textContent = `Last read failed (${data.consecutive_failures} consecutive): ${data.last_error}`;
  } else if ((data.notes || []).length) {
    errorNode.textContent = data.notes.join(' | ');
  } else {
    errorNode.textContent = '';
  }
}

/* ---------------- polling ---------------- */

function render(data) {
  renderHeader(data);
  renderAgents(data);
  renderPipeline(data);
  renderTask(data);
  renderFindings(data);
  renderEvidence(data);
  renderHistory(data);
  renderFooter(data);
}

let timer = null;

async function poll() {
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    /*
     * This is the browser losing the dashboard, not the dashboard losing GitHub. Mark
     * the link OFFLINE and leave every other value as it was: the last rendering is the
     * last thing known to be true, and blanking it would destroy information.
     */
    const linkChip = el('f-link');
    if (linkChip) {
      linkChip.dataset.link = 'OFFLINE';
      text(el('f-link-value'), 'OFFLINE');
    }
    const errorNode = el('f-error');
    if (errorNode) errorNode.textContent = `Cannot reach this dashboard's own /api/state: ${error.message}`;
  } finally {
    /*
     * The server decides the cadence and reports it, so a deployment that changes
     * BEGWORK_REFRESH_SECONDS does not need the page reloaded. The browser polls a
     * little faster than the server refreshes so a new round shows up promptly.
     */
    const seconds = Number(document.body.dataset.pollSeconds) || 5;
    clearTimeout(timer);
    timer = setTimeout(poll, seconds * 1000);
  }
}

/* Pause polling on a hidden tab: an all-day dashboard on a phone should not keep a
 * screen-off browser busy. Resume immediately when it comes back. */
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    clearTimeout(timer);
    poll();
  } else {
    clearTimeout(timer);
  }
});

poll();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* The dashboard works fine without it; installability is a convenience. */
    });
  });
}
