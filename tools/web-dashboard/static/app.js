/*
 * BEG_WORK Control Center — client renderer.
 *
 * The browser does no verification and no interpretation. /api/state has already been
 * verified server-side and sanitised; this file only lays it out. That split is what
 * keeps the GitHub token server-side: there is no build step that could inline it, and
 * the browser never talks to GitHub at all — only to this host's own endpoints.
 *
 * All insertion is via textContent or explicitly constructed elements. Nothing from the
 * payload is ever assigned to innerHTML, so a summary, an error message or a
 * waiting_for string that happens to contain markup is displayed as text.
 */
'use strict';

const DASH = '—';

/* A glyph per agent state, so cards never depend on colour alone. */
const STATE_GLYPH = {
  WORKING: '▶', WAITING: '⏸', REVIEW: '🔍', HANDOFF: '➜', PASS: '✓',
  CHANGES_REQUESTED: '↺', BLOCKED: '■', NOT_ACTIVE: '·', UNKNOWN: '?'
};

const STATUS_GLYPH = { VALID: '✓', STALE: '⏳', CONFLICT: '⚠', INVALID: '✕', UNKNOWN: '…' };

const AGENT_INITIAL = { GPT: 'GP', CODEX: 'CX', CLAUDE: 'CL' };

const el = (id) => document.getElementById(id);

function text(node, value) {
  if (!node) return;
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
  const dd = make('dd', mono ? 'mono' : null,
    (value === null || value === undefined || value === '') ? DASH : value);
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

/* ---------------------------------------------------- synthetic acceptance */

function renderSynthetic(data) {
  const banner = el('f-synthetic');
  if (!data.synthetic) {
    banner.hidden = true;
    document.body.removeAttribute('data-synthetic');
    return;
  }
  banner.hidden = false;
  document.body.setAttribute('data-synthetic', data.acceptance_scenario || 'yes');
  text(el('f-synthetic-text'),
    `${data.acceptance_notice || 'Synthetic acceptance data.'} ${data.acceptance_description || ''}`.trim());
}

/* ------------------------------------------------------------- masthead */

function renderMasthead(data) {
  const config = data.config || {};
  const header = data.header || {};

  text(el('f-repo'), header.repository || config.repository);
  text(el('f-branch'), header.branch || config.branch);

  const verifiedAt = el('f-verified-at');
  text(verifiedAt, localTime(data.last_verified_at) || 'never');
  verifiedAt.title = data.last_verified_at || 'no successful read yet';

  /*
   * The feed pill answers one question — can this page still believe what it shows?
   * OFFLINE when the last round failed, STALE when the last success is older than the
   * configured threshold, LIVE otherwise. It is deliberately separate from the
   * verification chip, which is about the control state's own protocol status.
   */
  let feed = 'LIVE';
  if (data.link === 'OFFLINE') feed = 'OFFLINE';
  else if (data.aged) feed = 'STALE';
  const feedNode = el('f-link');
  feedNode.dataset.feed = feed;
  text(el('f-link-value'), feed);
  text(el('f-age'), data.age_seconds === null || data.age_seconds === undefined ? '' : ago(data.age_seconds));
  feedNode.title = feed === 'LIVE'
    ? 'Connected; the last read is recent.'
    : feed === 'STALE'
      ? 'Connected, but the last successful read is older than the configured threshold.'
      : 'The last round failed. Showing the cached reading with its age.';

  const status = data.control_state_status || 'UNKNOWN';
  el('f-status').dataset.status = status;
  text(el('f-status-value'), status);
  el('f-status-glyph').textContent = STATUS_GLYPH[status] || STATUS_GLYPH.UNKNOWN;

  document.title = header.task_id
    ? `${header.task_id} ${header.state || ''} · BEG_WORK`.trim()
    : 'BEG_WORK Control Center';
}

/* ---------------------------------------------------------------- alerts */

function renderAlerts(data) {
  const header = data.header || {};
  const krum = header.krum_action || {};

  const krumNode = el('f-krum');
  krumNode.dataset.required = krum.required ? 'true' : 'false';
  krumNode.hidden = !krum.required;
  text(el('f-krum-value'), krum.required ? 'KRUM ACTION REQUIRED' : 'KRUM ACTION');
  text(el('f-krum-reason'), krum.reason || '');

  /*
   * An unverified round gets its own banner above the fold. Moving diagnostics into a
   * collapsed section must not hide the fact that the page is not verified.
   */
  const alertNode = el('f-statusalert');
  if (!data.available) {
    alertNode.hidden = false;
    text(el('f-statusalert-text'),
      'No control state has been read. Nothing on this page is verified.');
  } else if (!data.verified) {
    alertNode.hidden = false;
    const count = (data.findings || []).length;
    text(el('f-statusalert-text'),
      `This round did not verify (${data.control_state_status}). ` +
      `${count} finding${count === 1 ? '' : 's'} — open “Verification & evidence” below. ` +
      'Treat every value on this page as unconfirmed.');
  } else {
    alertNode.hidden = true;
    text(el('f-statusalert-text'), '');
  }
}

/* ----------------------------------------------------------- agent cards */

function renderAgents(data) {
  const host = el('f-agents');
  host.textContent = '';
  (data.agents || []).forEach((agent) => {
    const card = make('article', 'agent' + (agent.is_current ? ' agent--current' : ''));
    card.dataset.agent = agent.key;
    card.dataset.state = agent.state || 'UNKNOWN';

    const head = make('div', 'agent__head');
    head.appendChild(make('span', 'agent__badge', AGENT_INITIAL[agent.key] || '··'));
    const names = make('div', 'agent__names');
    names.appendChild(make('span', 'agent__name', agent.name));
    names.appendChild(make('span', 'agent__role', agent.role));
    head.appendChild(names);
    if (agent.is_current) head.appendChild(make('span', 'agent__now', 'current'));
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

/* ------------------------------------------------------------ focus panel */

function renderFocus(data) {
  const header = data.header || {};
  const task = data.task;

  text(el('f-task'), header.task_id);
  text(el('f-cycle'), header.cycle_label || header.cycle_id);
  text(el('f-wave'), header.wave);
  text(el('f-flow'), header.flow);
  text(el('f-stage'), (header.progress || {}).stage);
  text(el('f-workid'), task ? task.current_work_id : null);

  const stateNode = el('f-state');
  text(stateNode, header.state_display);
  stateNode.dataset.state = header.state || 'UNKNOWN';

  const note = el('f-verified');
  if (!data.available) note.textContent = 'no snapshot has been read yet';
  else if (data.verified) note.textContent = 'verified against the bytes read this round';
  else note.textContent = 'NOT verified this round — treat as unconfirmed';

  text(el('f-focus-hint'), task
    ? `${task.current_agent_name || DASH} · ${task.current_role || DASH} · step ${task.pipeline_step || DASH}`
    : 'No task is projected: there is no verified snapshot.');

  renderProgress(data);
}

function renderProgress(data) {
  const host = el('f-progress');
  host.textContent = '';
  const progress = (data.header || {}).progress || {};
  if (!progress.mode && !progress.workflow_position) return;

  /*
   * The stage is always safe to show, but it must carry its own verification status:
   * a stage read from a round that did not verify is a claim, not a fact.
   */
  const verified = progress.stage_verified === true;
  if (progress.mode) {
    const label = `${progress.stage || DASH} · ${progress.mode}${verified ? '' : ' · UNVERIFIED'}`;
    const chip = make('span', 'progress__stage', label);
    if (!verified) chip.classList.add('progress__stage--unverified');
    host.appendChild(chip);
  }

  /*
   * Numbers and the bar are drawn only when the server says they may be. The server
   * withholds them on STAGE_ONLY and on any unverified round, so a state claiming an
   * arithmetically impossible "3 of 8 · 90%" cannot put a 90%-full bar on the wall.
   * The browser never recomputes or infers a figure of its own.
   */
  const withheld = progress.numbers_withheld
    || progress.percent === null || progress.percent === undefined;

  if (!withheld) {
    host.appendChild(make('p', 'progress__note',
      `${progress.completed} of ${progress.total} verified milestones · ${progress.percent}%`));
    const bar = make('div', 'progress__bar');
    const fill = make('div', 'progress__fill');
    fill.style.width = `${Math.max(0, Math.min(100, progress.percent))}%`;
    bar.appendChild(fill);
    host.appendChild(bar);
    return;
  }

  host.appendChild(make('p', 'progress__note',
    progress.withheld_reason || 'No proven percentage is published for this task.'));

  /*
   * The stage meter is six discrete segments marking WHERE the workflow is, derived
   * from the verified pipeline_step. It is deliberately segmented rather than a filled
   * bar, and labelled as a position, because nothing here proves how much is done.
   */
  const position = progress.workflow_position;
  if (position && position.index && position.total) {
    const meter = make('div', 'meter');
    for (let i = 1; i <= position.total; i += 1) {
      const seg = make('span', 'meter__seg');
      if (i < position.index) seg.classList.add('meter__seg--before');
      if (i === position.index) seg.classList.add('meter__seg--current');
      meter.appendChild(seg);
    }
    host.appendChild(meter);
    host.appendChild(make('p', 'progress__note',
      `Stage ${position.index} of ${position.total} — ${position.label}. ` +
      'Workflow position, not a completion percentage.'));
  }
}

/* ------------------------------------------------------------ next steps */

function renderNextSteps(data) {
  const host = el('f-next-steps');
  host.textContent = '';
  const steps = data.next_steps;

  if (!steps) {
    host.appendChild(make('p', 'empty', 'No next step is projected: there is no verified snapshot.'));
  } else {
    const list = make('dl', 'steps');
    row(list, 'step', 'Next', steps.next_agent_name, true);
    row(list, 'step', 'Waiting for', steps.waiting_for);
    row(list, 'step', 'Dispatch', steps.dispatch_state, true);
    if (steps.requires_krum) row(list, 'step', 'Krum', steps.krum_reason);
    host.appendChild(list);
  }

  const gate = el('f-gate');
  text(gate, data.gate);
  gate.classList.toggle('gate--blocked', Boolean(steps && steps.blocked));
}

/* -------------------------------------------------------------- workflow */

function renderWorkflow(data) {
  const host = el('f-workflow');
  host.textContent = '';
  const activeState = (data.header || {}).state || '';

  (data.workflow || []).forEach((step) => {
    const item = make('li', 'wf__step');
    item.dataset.relative = step.relative || 'unknown';
    item.dataset.label = step.label;
    if (step.relative === 'current') item.dataset.state = activeState;

    item.appendChild(make('span', 'wf__label', step.label));
    item.appendChild(make('span', 'wf__agent', step.agent || 'protocol'));
    /* Name the canonical step this label renders, so the mapping is auditable. NEXT
     * renders no canonical step at all, and says so rather than naming one. */
    item.appendChild(make('span', 'wf__canon', step.canonical_step || 'no canonical step'));
    if (step.derived) item.appendChild(make('span', 'wf__derived', 'derived'));
    if (step.badge) item.appendChild(make('span', 'wf__badge', step.badge));

    host.appendChild(item);
  });
}

/* ----------------------------------------------------------------- tasks */

function renderTasks(data) {
  const body = el('f-tasks-body');
  body.textContent = '';
  const table = data.task_table || { rows: [], note: '' };

  if (!table.rows.length) {
    const tr = make('tr');
    const td = make('td', 'empty', 'No task row is proven by the current snapshot.');
    td.colSpan = 7;
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    table.rows.forEach((item) => {
      const tr = make('tr');
      tr.appendChild(make('td', 'cell-id', item.id));
      tr.appendChild(make('td', 'cell-mono', item.task));

      const statusCell = make('td');
      const pill = make('span', 'pill', item.status_verified ? item.status : `${item.status} (UNVERIFIED)`);
      pill.dataset.state = item.status_verified ? item.status : 'UNKNOWN';
      statusCell.appendChild(pill);
      tr.appendChild(statusCell);

      tr.appendChild(make('td', 'cell-mono', item.progress));

      const agentCell = make('td');
      const tag = make('span', 'agent-tag');
      tag.dataset.agent = item.current_agent_key || '';
      tag.appendChild(make('span', 'agent-tag__dot'));
      tag.appendChild(make('span', null, item.current_agent));
      agentCell.appendChild(tag);
      tr.appendChild(agentCell);

      tr.appendChild(make('td', 'cell-mono', item.cycle));
      tr.appendChild(make('td', 'cell-mono', item.updated));
      body.appendChild(tr);
    });
  }
  text(el('f-tasks-note'), table.note);
}

/* -------------------------------------------------------------- timeline */

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

    /* Summary and provenance share one line: eleven three-line cards turned the
     * activity panel into half the page, which is the wrong emphasis for a control
     * center. Nothing is dropped — the head SHA and the evidence link are still here. */
    const body = make('p', 'event__summary');
    if (event.summary) body.appendChild(document.createTextNode(event.summary));
    const foot = make('span', 'event__foot');
    foot.appendChild(make('span', null, `head ${shortSha(event.head_sha)}`));
    if (event.source_url) foot.appendChild(link(event.source_url, 'evidence'));
    body.appendChild(foot);
    item.appendChild(body);

    host.appendChild(item);
  });
}

/* ----------------------------------------------------------- diagnostics */

function renderFindings(data) {
  const host = el('f-findings');
  host.textContent = '';
  const findings = data.findings || [];
  text(el('f-diag-count'), findings.length
    ? `${findings.length} finding${findings.length === 1 ? '' : 's'}`
    : 'no findings');

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
      ` · verdict ${review.verdict || DASH} on head ${shortSha(review.reviewed_head_sha)}`
    ], matchLabel(review.blob_sha, review.observed_blob_sha)));
  }

  if (evidence.pull_request) {
    const pr = evidence.pull_request;
    let match;
    if (!pr.observed_head_sha) {
      match = make('span', 'ev__match ev__match--none', 'PR metadata not read this round — exact head unverified');
    } else if (pr.observed_head_sha.toLowerCase() === String(pr.cited_head_sha).toLowerCase()) {
      match = make('span', 'ev__match ev__match--ok',
        `live head matches ${shortSha(pr.observed_head_sha)}${pr.observed_draft ? ' · still Draft' : ' · NOT Draft'}`);
    } else {
      match = make('span', 'ev__match ev__match--bad', `HEAD MOVED — live head is ${shortSha(pr.observed_head_sha)}`);
    }
    host.appendChild(evidenceItem('DRAFT PR', [
      pr.url ? link(pr.url, `#${pr.number}`) : `#${pr.number}`,
      `${pr.draft ? ' (Draft)' : ''} · cited exact head ${shortSha(pr.cited_head_sha)}`
    ], match));
  }

  if (evidence.handoff) {
    host.appendChild(evidenceItem('HANDOFF', [
      evidence.handoff.url ? link(evidence.handoff.url, 'comment') : DASH,
      ` · head ${shortSha(evidence.handoff.head_sha)} · ${evidence.handoff.at || DASH}`
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
    shortSha(evidence.control_state_commit_sha), ` — ${evidence.control_state_note}`
  ], null));
}

function renderFeedDetail(data) {
  const config = data.config || {};
  text(el('f-next'), data.next_attempt_in === null || data.next_attempt_in === undefined
    ? DASH : `${Math.round(data.next_attempt_in)}s`);
  text(el('f-protocol'), (data.header || {}).protocol_version
    ? `v${data.header.protocol_version} · ${(data.header || {}).validation_mode || DASH}`
    : DASH);
  /*
   * Whether a credential is configured is operationally useful; its value is never sent
   * to the browser, so there is nothing here to leak.
   */
  text(el('f-token'), config.token_configured ? 'configured (server-side)' : 'none (anonymous reads)');
  text(el('f-rounds'), data.rounds);

  const errorNode = el('f-error');
  if (data.last_error) {
    errorNode.textContent = `Last read failed (${data.consecutive_failures} consecutive): ${data.last_error}`;
  } else if ((data.notes || []).length) {
    errorNode.textContent = data.notes.join(' | ');
  } else {
    errorNode.textContent = '';
  }
}

/* ------------------------------------------------------------------ poll */

function render(data) {
  renderSynthetic(data);
  renderMasthead(data);
  renderAlerts(data);
  renderAgents(data);
  renderFocus(data);
  renderNextSteps(data);
  renderWorkflow(data);
  renderTasks(data);
  renderHistory(data);
  renderFindings(data);
  renderEvidence(data);
  renderFeedDetail(data);
}

/*
 * An acceptance scenario is opt-in per page load: /?acceptance=stale. The server only
 * answers when acceptance mode is enabled there, so a production deployment cannot be
 * put into this state from the URL.
 */
function endpoint() {
  const scenario = new URLSearchParams(window.location.search).get('acceptance');
  return scenario ? `/api/acceptance/${encodeURIComponent(scenario)}` : '/api/state';
}

let timer = null;

async function poll() {
  try {
    const response = await fetch(endpoint(), { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    /*
     * This is the browser losing the dashboard, not the dashboard losing GitHub. Mark
     * the feed OFFLINE and leave every other value as it was: the last rendering is the
     * last thing known to be true, and blanking it would destroy information.
     */
    const feedNode = el('f-link');
    if (feedNode) {
      feedNode.dataset.feed = 'OFFLINE';
      text(el('f-link-value'), 'OFFLINE');
    }
    const errorNode = el('f-error');
    if (errorNode) errorNode.textContent = `Cannot reach this dashboard's own API: ${error.message}`;
  } finally {
    const seconds = Number(document.body.dataset.pollSeconds) || 5;
    clearTimeout(timer);
    timer = setTimeout(poll, seconds * 1000);
  }
}

/* Pause polling on a hidden tab: an all-day dashboard on a phone should not keep a
 * screen-off browser busy. Resume immediately when it comes back. */
document.addEventListener('visibilitychange', () => {
  clearTimeout(timer);
  if (document.visibilityState === 'visible') poll();
});

poll();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* The dashboard works fine without it; installability is a convenience. */
    });
  });
}
