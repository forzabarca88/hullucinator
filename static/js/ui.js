/* ── UI Utilities ─────────────────────────────────────────────── */

const API = '/api';

const $ = id => document.getElementById(id);

async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const resp = await fetch(API + path, { ...opts, headers });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  return resp.json();
}

/* ── Toast Notifications ───────────────────────────────────────── */
function toast(msg, type = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

/* ── HTML Escaping ─────────────────────────────────────────────── */
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

/* ── Status Badge ──────────────────────────────────────────────── */
function statusBadge(status) {
  const cls = {
    pending: 'badge-pending',
    summary_generated: 'badge-summary_generated',
    outline_generated: 'badge-outline_generated',
    in_progress: 'badge-in_progress',
    completed: 'badge-completed',
    reviewing: 'badge-reviewing',
    reviewed: 'badge-reviewed',
    failed: 'badge-failed',
  };
  return `<span class="badge ${cls[status] || 'badge-pending'}">${status.replace(/_/g,' ')}</span>`;
}

/* ── Progress Polling ──────────────────────────────────────────── */
let pollingInterval = null;
let pollingBookId = null;

function startPolling(bookId, onDone) {
  stopPolling();
  pollingBookId = bookId;
  pollingInterval = setInterval(async () => {
    if (!pollingBookId) return;
    try {
      const book = await apiFetch('/books/' + pollingBookId);
      const isDone = ['completed', 'reviewed', 'failed'].includes(book.status);
      if (onDone) onDone(book);
      if (isDone) {
        stopPolling();
        if (onDone) onDone(book);
      }
    } catch (err) {
      console.error('poll error:', err);
    }
  }, 3000);
}

function stopPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
  }
  pollingBookId = null;
}
