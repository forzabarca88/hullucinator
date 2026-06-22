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

/* ── Lightweight Markdown Renderer ────────────────────────────── */
// Self-contained — no external dependencies (CSP blocks CDN loads).
// Handles: headings, bold, italic, code blocks, inline code,
// unordered/ordered lists, blockquotes, horizontal rules, paragraphs.
function renderMarkdown(src) {
  if (!src) return '';
  let text = String(src);

  // Normalize line endings
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  // Extract fenced code blocks (``` ... ```) and preserve them
  const codeBlocks = [];
  text = text.replace(/```([\s\S]*?)```/g, (_, code) => {
    const lang = code.startsWith('\n') ? code.trim() : code;
    const lines = lang.split('\n');
    const language = lines[0].trim().toLowerCase() || '';
    const body = lines.slice(1).join('\n').trim();
    const idx = codeBlocks.length;
    codeBlocks.push({ language, body: esc(body) });
    return `%%CODEBLOCK_${idx}%%`;
  });

  // Extract inline code (`code`) before other processing
  const inlineCodes = [];
  text = text.replace(/`([^\n`]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(esc(code));
    return `%%INLINE_${idx}%%`;
  });

  // Escape HTML in remaining text
  text = esc(text);

  // Restore code blocks
  text = text.replace(/%%CODEBLOCK_(\d+)%%/g, (_, idx) => {
    const { language, body } = codeBlocks[+idx];
    const langAttr = language ? ` class="language-${esc(language)}"` : '';
    return `\n<pre><code${langAttr}>${body}</code></pre>\n`;
  });

  // Restore inline code
  text = text.replace(/%%INLINE_(\d+)%%/g, (_, idx) => {
    return `<code>${inlineCodes[+idx]}</code>`;
  });

  // Horizontal rules
  text = text.replace(/^(?:---+|___+|\*\*\*+)\s*$/gm, '<hr>');

  // Headings
  text = text.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
  text = text.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
  text = text.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
  text = text.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
  text = text.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
  text = text.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

  // Bold and italic (order matters: bold+italic first)
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  text = text.replace(/___(.+?)___/g, '<strong><em>$1</em></strong>');
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__(.+?)__/g, '<strong>$1</strong>');
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
  text = text.replace(/_(.+?)_/g, '<em>$1</em>');

  // Blockquotes
  text = text.replace(/^&gt;\s+(.+)$/gm, '<blockquote>$1</blockquote>');

  // Merge consecutive blockquotes
  text = text.replace(/(<blockquote>)(?:<\/blockquote>\n<blockquote>)*(\n?)([\s\S]*?)(<\/blockquote>)/g, (_, open, sep, body, close) => {
    return `<blockquote>${body.trim()}</blockquote>`;
  });

  // Process paragraphs and lists
  const lines = text.split('\n');
  const result = [];
  let inUl = false;
  let inOl = false;
  let inP = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Skip empty lines (close open blocks)
    if (line.trim() === '') {
      if (inUl) { result.push('</ul>'); inUl = false; }
      if (inOl) { result.push('</ol>'); inOl = false; }
      if (inP) { result.push('</p>'); inP = false; }
      result.push('');
      continue;
    }

    // Unordered list item
    const ulMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (ulMatch) {
      if (inOl) { result.push('</ol>'); inOl = false; }
      if (inP) { result.push('</p>'); inP = false; }
      if (!inUl) { result.push('<ul>'); inUl = true; }
      result.push(`<li>${ulMatch[1]}</li>`);
      continue;
    }

    // Ordered list item
    const olMatch = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (olMatch) {
      if (inUl) { result.push('</ul>'); inUl = false; }
      if (inP) { result.push('</p>'); inP = false; }
      if (!inOl) { result.push('<ol>'); inOl = true; }
      result.push(`<li>${olMatch[1]}</li>`);
      continue;
    }

    // Close list blocks if line is not a list item
    if (inUl) { result.push('</ul>'); inUl = false; }
    if (inOl) { result.push('</ol>'); inOl = false; }

    // Pre/code blocks and horizontal rules are standalone
    if (line.startsWith('<pre>') || line.startsWith('<hr>')) {
      if (inP) { result.push('</p>'); inP = false; }
      result.push(line);
      continue;
    }

    // Blockquotes
    if (line.startsWith('<blockquote>')) {
      if (inP) { result.push('</p>'); inP = false; }
      result.push(line);
      continue;
    }

    // Headings
    if (line.match(/^<h[1-6]>/)) {
      if (inP) { result.push('</p>'); inP = false; }
      result.push(line);
      continue;
    }

    // Regular text — wrap in paragraph
    if (!inP) { result.push('<p>'); inP = true; }
    else { result.push('<br>'); }
    result.push(line);
  }

  if (inUl) result.push('</ul>');
  if (inOl) result.push('</ol>');
  if (inP) result.push('</p>');

  return result.join('\n').trim();
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
      const isDone = isTerminalStatus(book.status);
      pollingCallback(book);
      if (isDone) {
        stopPolling();
        pollingCallback(book);
      }
    } catch (err) {
      console.error('poll error:', err);
    }
  }, SHARED_CONFIG?.ui?.polling_interval_ms ?? 3000);
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
const LIBRARY_POLL_INTERVAL = () => SHARED_CONFIG?.ui?.library_polling_interval_ms ?? 10000;

function startLibraryPolling(onUpdate) {
  stopLibraryPolling();
  libraryPollingInterval = setInterval(async () => {
    try {
      onUpdate();
    } catch (err) {
      console.error('library poll error:', err);
    }
  }, LIBRARY_POLL_INTERVAL());
}

function stopLibraryPolling() {
  if (libraryPollingInterval) {
    clearInterval(libraryPollingInterval);
    libraryPollingInterval = null;
  }
}
