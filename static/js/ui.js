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
// (L5 fix: regex-based escaping is faster than DOM element creation for large strings)
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ── Status Badge ──────────────────────────────────────────────── */
function statusBadge(status) {
  const textMap = {
    pending: 'pending',
    summary_generated: 'summary',
    outline_generated: 'outline',
    in_progress: 'in progress',
    completed: 'completed',
    reviewing: 'reviewing',
    reviewed: 'reviewed',
    failed: 'failed',
  };
  const label = textMap[status] || status.replace(/_/g, ' ');
  return `<span class="status-label status-${status}">${label}</span>`;
}

/* ── Progress Polling ──────────────────────────────────────────── */
let pollingInterval = null;
let pollingBookId = null;
let pollingCallback = null;

function startPolling(bookId, onDone) {
  stopPolling();
  pollingBookId = bookId;
  pollingCallback = onDone;
  pollingInterval = setInterval(async () => {
    // (L7 fix: guard against stale callbacks from previous polling sessions)
    if (!pollingBookId || !pollingCallback) return;
    try {
      const book = await apiFetch('/books/' + pollingBookId);
      // Double-check that this callback still belongs to the current polling session
      if (pollingBookId !== book.id) return;
      const isDone = ['completed', 'reviewed', 'failed'].includes(book.status);
      pollingCallback(book);
      if (isDone) {
        stopPolling();
        pollingCallback(book);
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
  pollingCallback = null;
}

/* ── Library Auto-Refresh ───────────────────────────────────────── */
let libraryPollingInterval = null;
const LIBRARY_POLL_INTERVAL = 10000; // 10 seconds

function startLibraryPolling(onUpdate) {
  stopLibraryPolling();
  libraryPollingInterval = setInterval(async () => {
    try {
      onUpdate();
    } catch (err) {
      console.error('library poll error:', err);
    }
  }, LIBRARY_POLL_INTERVAL);
}

function stopLibraryPolling() {
  if (libraryPollingInterval) {
    clearInterval(libraryPollingInterval);
    libraryPollingInterval = null;
  }
}
