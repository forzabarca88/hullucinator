/* ── Main Application ──────────────────────────────────────────── */

/* ── State ─────────────────────────────────────────────────────── */
let tags = [];
let currentBookId = null;

/* ── Tag Input ─────────────────────────────────────────────────── */
function initTags() {
  const input = $('tagInput');
  if (!input) return;

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.value.trim()) {
      e.preventDefault();
      const tag = e.target.value.trim();
      if (!tags.includes(tag)) {
        tags.push(tag);
        renderTagBadges();
      }
      e.target.value = '';
    }
  });

  document.body.addEventListener('click', e => {
    const btn = e.target.closest('.tag-badge button');
    if (btn) {
      tags.splice(+btn.dataset.idx, 1);
      renderTagBadges();
    }
  });
}

function renderTagBadges() {
  const container = $('tagBadges');
  if (!container) return;
  container.innerHTML = tags.map((t, i) =>
    `<span class="tag-badge">${esc(t)}<button data-idx="${i}">✕</button></span>`
  ).join('');
}

/* ── Create Book ───────────────────────────────────────────────── */
function initCreateForm() {
  // Live character counter for the prompt textarea
  const promptEl = $('prompt');
  const counterEl = $('promptCounter');
  if (promptEl && counterEl) {
    promptEl.addEventListener('input', () => {
      const len = promptEl.value.length;
      counterEl.textContent = len.toLocaleString() + ' characters';
      counterEl.className = 'field-hint' + (len > 10000 ? ' prompt-warn' : '');
    });
  }

  $('createForm').addEventListener('submit', async e => {
    e.preventDefault();

    // Client-side validation — fail fast with clear messages
    const title = $('title').value.trim();
    const prompt = $('prompt').value.trim();
    if (!title) {
      toast('Please enter a book title.', 'error');
      $('title').focus();
      return;
    }
    if (!prompt) {
      toast('Please enter a prompt or concept.', 'error');
      $('prompt').focus();
      return;
    }

    // Guard: must be configured
    if (!appConfigured) {
      toast('Configure your AI provider first.', 'error');
      $('setupOverlay').classList.add('active');
      $('mainContent').style.display = 'none';
      $('header').style.display = 'none';
      return;
    }

    const btn = $('createBtn');
    btn.disabled = true;
    btn.textContent = 'Queuing…';

    try {
      const turns = parseInt($('maxTurns')?.value);
      const data = await apiFetch('/books/create', {
        method: 'POST',
        body: JSON.stringify({
          title: title,
          prompt: prompt,
          tags: tags,
          length: $('bookLength')?.value || 'novel',
          review_max_turns: isNaN(turns) ? 2 : turns,
          skip_review: false,
        }),
      });
      toast('Book "' + data.book_id.slice(0, 8) + '…" queued!', 'success');
      $('title').value = '';
      $('prompt').value = '';
      tags = [];
      renderTagBadges();
      loadBooks();
    } catch (err) {
      toast('Error: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Generate Book';
    }
  });
}

/* ── Library ───────────────────────────────────────────────────── */
/* ── Library (L6 fix: keyed reconciliation to minimize DOM thrashing) ── */
async function loadBooks() {
  try {
    const books = await apiFetch('/books');
    const list = $('booksList');
    if (!list) return;

    const activeStatuses = new Set(['pending', 'summary_generated', 'outline_generated', 'in_progress', 'reviewing']);
    const hasActive = books.some(b => activeStatuses.has(b.status));

    if (!books.length) {
      list.innerHTML = '<div class="empty-state"><hr><p>Your shelves are empty. Submit your first manuscript above.</p></div>';
      stopLibraryPolling();
      return;
    }

    // Remove the initial empty-state div from the HTML skeleton
    const emptyState = list.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    // Build a set of expected book IDs
    const expectedIds = new Set(books.map(b => b.id));
    const booksMap = new Map(books.map(b => [b.id, b]));

    // Remove cards for books that no longer exist
    for (const card of list.querySelectorAll('.book-card')) {
      if (!expectedIds.has(card.dataset.id)) {
        card.remove();
      }
    }

    // Update or create cards for each book
    for (const b of books) {
      let card = list.querySelector(`.book-card[data-id="${b.id}"]`);
      const p = b.progress || {};
      const pct = p.percentage || 0;
      const isDone = b.status === 'completed' || b.status === 'reviewed';
      const isFail = b.status === 'failed';
      const pClass = isDone ? 'complete' : isFail ? 'fail' : '';

      const html = buildBookCardHtml(b, p, pct, isDone, isFail, pClass);

      if (!card) {
        // New book — create card
        const frag = document.createElement('div');
        frag.innerHTML = html;
        list.appendChild(frag.firstElementChild);
        list.querySelector(`.book-card[data-id="${b.id}"]`).onclick = () => openDetail(b.id);
      } else {
        // Existing book — check if update is needed
        if (card.innerHTML !== html) {
          card.innerHTML = html;
        }
      }
      // Bind click on the card (opens detail) but not on the delete button
      const c = list.querySelector(`.book-card[data-id="${b.id}"]`);
      c.onclick = () => openDetail(b.id);
      // Bind delete button
      const deleteBtn = c.querySelector('.book-delete-btn');
      if (deleteBtn) {
        deleteBtn.onclick = (e) => {
          e.stopPropagation();
          deleteBook(b.id, b.title);
        };
      }
    }

    // Auto-refresh: start polling if any books are active, stop otherwise
    if (hasActive) {
      startLibraryPolling(loadBooks);
    } else {
      stopLibraryPolling();
    }
  } catch (err) {
    console.error('loadBooks error:', err);
  }
}

function buildBookCardHtml(b, p, pct, isDone, isFail, pClass) {
  let tagsHtml = (b.tags || []).map(t => `<span class="tag-badge">${esc(t)}</span>`).join('');
  let lengthBadge = b.length ? `<span class="status-label" style="color:var(--status-pending);background:rgba(91,123,138,0.08)">${esc(b.length)}</span>` : '';

  return `<div class="book-card" data-id="${b.id}">
    <button class="book-delete-btn" data-delete-id="${b.id}" title="Delete book">Delete</button>
    <div class="book-title">${esc(b.title)}</div>
    <div class="book-meta">
      ${statusBadge(b.status)}
      ${lengthBadge}
      ${tagsHtml}
    </div>
    <div class="book-prompt">${esc(b.prompt)}</div>
    ${pct > 0 ? `<div class="progress-bar"><div class="progress-fill ${pClass}" style="width:${pct}%"></div></div>` : ''}
    ${p.current_step && p.current_step !== b.status ? `<small style="color:var(--ash)">${esc(p.current_step)}</small>` : ''}
  </div>`;
}

/* ── Detail Modal ──────────────────────────────────────────────── */
function initModal() {
  $('detailClose').addEventListener('click', closeModal);
  $('detailOverlay').addEventListener('click', e => {
    if (e.target === $('detailOverlay')) closeModal();
  });
}

/* ── Modal Action Listeners (CSP-safe — no inline onclick) ─────── */
function attachModalActionListeners(bookId) {
  const detailContent = $('detailContent');
  detailContent.querySelectorAll('button[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      if (action === 'review') triggerReview(bookId);
      else if (action === 'retry') retryBook(bookId);
      else if (action === 'delete') deleteBook(bookId, $('detailTitle').textContent);
    });
  });
}

async function openDetail(bookId) {
  currentBookId = bookId;
  try {
    const book = await apiFetch('/books/' + bookId);
    $('detailTitle').textContent = book.title;
    $('detailContent').innerHTML = renderDetail(book);
    attachModalActionListeners(bookId);

    $('detailOverlay').classList.add('active');

    // Poll for progress if still in progress
    if (['pending', 'summary_generated', 'outline_generated', 'in_progress', 'reviewing'].includes(book.status)) {
      startPolling(bookId, async (updatedBook) => {
        // Update progress bar in modal
        const pBar = $('detailContent').querySelector('.progress-fill');
        if (pBar) {
          const pct = updatedBook.progress?.percentage || 0;
          pBar.style.width = pct + '%';
          pBar.className = 'progress-fill ' +
            (updatedBook.status === 'failed' ? 'fail' :
             updatedBook.status === 'reviewed' ? 'complete' : '');
        }
        const pText = $('detailContent').querySelector('.progress-bar + p');
        if (pText) {
          pText.textContent = `${esc(updatedBook.progress?.current_step || updatedBook.status)} (${updatedBook.progress?.percentage || 0}%)`;
        }
        // Refresh library
        loadBooks();
      });
    }
  } catch (err) {
    toast('Error loading book: ' + err.message, 'error');
  }
}

function closeModal() {
  $('detailOverlay').classList.remove('active');
  stopPolling();
  currentBookId = null;
}

function renderDetail(book) {
  let html = '';

  // Settings used when creating this book
  html += `<div class="modal-section">
    <h3>Settings</h3>
    <div class="detail-settings">
      <div class="detail-setting"><span class="detail-label">Prompt</span><div class="detail-value">${esc(book.prompt)}</div></div>
      <div class="detail-setting"><span class="detail-label">Length</span><div class="detail-value">${esc(book.length || 'novel')}</div></div>
      ${book.tags && book.tags.length ? `<div class="detail-setting"><span class="detail-label">Tags</span><div class="detail-value">${book.tags.map(t => `<span class="tag-badge">${esc(t)}</span>`).join(' ')}</div></div>` : ''}
      ${book.review_max_turns ? `<div class="detail-setting"><span class="detail-label">Max Review Turns</span><div class="detail-value">${book.review_max_turns}</div></div>` : ''}
    </div>
  </div>`;

  // Status
  html += `<div class="modal-section">
    <h3>Status</h3>
    <p>${statusBadge(book.status)}</p>
  </div>`;

  // Progress bar
  if (book.progress) {
    const p = book.progress;
    const pct = p.percentage || 0;
    const isDone = book.status === 'completed' || book.status === 'reviewed';
    const isFail = book.status === 'failed';
    const pClass = isDone ? 'complete' : isFail ? 'fail' : '';
    html += `<div class="modal-section">
      <h3>Progress</h3>
      <div class="progress-bar"><div class="progress-fill ${pClass}" style="width:${pct}%"></div></div>
      <p style="margin-top:0.3rem;font-size:0.85rem">${esc(p.current_step || book.status)} (${pct}%)</p>
      ${p.total_chapters ? `<small style="color:var(--ash)">Chapters: ${p.chapters_completed || 0}/${p.total_chapters}</small>` : ''}
      ${p.error ? `<p style="color:var(--status-error);margin-top:0.3rem">Error: ${esc(p.error)}</p>` : ''}
    </div>`;
  }

  // Summary
  if (book.summary) {
    html += `<div class="modal-section"><h3>Summary</h3><pre>${esc(book.summary)}</pre></div>`;
  }

  // Outline
  if (book.outline && book.outline.length) {
    html += `<div class="modal-section"><h3>Outline</h3><ol>${book.outline.map(c => `<li>${esc(c)}</li>`).join('')}</ol></div>`;
  }

  // Chapters
  if (book.chapters) {
    const entries = Object.entries(book.chapters);
    html += `<div class="modal-section"><h3>Chapters (${entries.length})</h3>`;
    for (const [title, content] of entries) {
      html += `<details><summary>${esc(title)}</summary>
        <pre>${esc(content)}</pre></details>`;
    }
    html += `</div>`;
  }

  // Review Section
  if (book.review) {
    html += buildReviewSection(book.review, book.review_history);
  }

  // Actions
  html += `<div class="modal-section" style="display:flex;gap:0.5rem;flex-wrap:wrap">`;
  if (book.status === 'completed' || book.status === 'reviewed') {
    html += `<a class="btn btn-primary btn-sm" href="${API}/books/${book.id}/export/epub">Download EPUB</a>`;
    html += `<a class="btn btn-secondary btn-sm" href="${API}/books/${book.id}/export/pdf">Download PDF</a>`;
  }
  if (book.status === 'completed') {
    html += `<button class="btn btn-secondary btn-sm" data-action="review">Trigger Review</button>`;
  }
  if (book.status === 'failed') {
    html += `<button class="btn btn-secondary btn-sm" data-action="retry">Retry</button>`;
  }
  html += `<button class="btn btn-secondary btn-sm" data-action="delete" style="color:var(--status-error);border-color:var(--status-error)">Delete</button>`;
  html += `</div>`;

  return html;}

/* ── Review Section Renderer ───────────────────────────────────── */
function buildReviewSection(review, history) {
  let html = `<div class="review-section">`;
  html += `<h3>Review Results</h3>`;

  const score = review.overall_score ?? 0;
  const verdict = review.verdict || 'unknown';
  const scoreClass = score >= 7 ? 'good' : score >= 4 ? 'ok' : 'bad';
  const passClass = verdict === 'ready' ? 'passed' : 'failed';

  html += `<div class="review-score ${scoreClass}">${score}/10</div>`;
  html += `<div class="review-verdict ${passClass}">${verdict === 'ready' ? 'Approved' : 'Needs Revision'}</div>`;

  if (review.max_turns_reached) {
    html += `<p style="color:var(--brass);text-align:center;font-size:0.85rem;margin-bottom:0.5rem">
      Max turns reached — some issues may remain</p>`;
  }

  if (review.critique) {
    html += `<details style="margin-top:0.5rem"><summary style="cursor:pointer;font-family:var(--body-font);color:var(--ash);font-size:0.85rem;font-weight:500">View Full Critique</summary>
      <div class="review-critique">${esc(review.critique)}</div></details>`;
  }

  // Correction audit trail
  if (review.corrections && review.corrections.length) {
    html += `<h4 style="margin-top:0.8rem;font-size:0.9rem;color:var(--ink)">Corrections Applied</h4>`;
    for (const c of review.corrections) {
      html += `<div class="correction-item">
        <span class="corr-chapter">${esc(c.chapter)}</span>
        <span class="corr-type">[${esc(c.issue_type)}]</span>
        <div style="margin-top:0.2rem;font-size:0.8rem;color:var(--ash)">${esc(c.issue_description)}</div>
      </div>`;
    }
  }

  // Iteration history
  if (history && history.length > 1) {
    html += `<h4 style="margin-top:1rem;font-family:var(--display-font);font-size:15px;font-weight:600;color:var(--ink)">Review History (${history.length} turns)</h4>`;
    for (const turn of history) {
      const tScore = turn.overall_score ?? '?';
      const tVerdict = turn.verdict || '?';
      const tScoreClass = tScore >= 7 ? 'good' : tScore >= 4 ? 'ok' : 'bad';
      const tPassClass = tVerdict === 'ready' ? 'passed' : 'failed';
      html += `<div style="background:var(--page);padding:0.5rem 0.7rem;border:1px solid var(--vellum);border-radius:0;margin-bottom:0.3rem;font-size:13px">
        <span style="font-family:var(--body-font);font-weight:600">Turn ${turn.turn}</span>: Score <span class="review-score ${tScoreClass}" style="font-size:14px;font-family:var(--display-font);font-weight:700;display:inline">${tScore}/10</span>
        — <span class="review-verdict ${tPassClass}" style="font-size:0.85rem">${tVerdict}</span>
        ${turn.corrections && turn.corrections.length ? `(${turn.corrections.length} corrections)` : ''}
      </div>`;
    }
  }

  html += `</div>`;
  return html;
}

/* ── Trigger Review ────────────────────────────────────────────── */
async function triggerReview(bookId) {
  try {
    const res = await apiFetch('/books/' + bookId + '/review', { method: 'POST' });
    toast('Review started (max ' + res.max_turns + ' turns)', 'success');
    closeModal();
    loadBooks();
    openDetail(bookId);
  } catch (err) {
    toast('Review error: ' + err.message, 'error');
  }
}

/* ── Retry Book ────────────────────────────────────────────────── */
async function retryBook(bookId) {
  if (!confirm('Restart generation for this book?')) return;
  try {
    const book = await apiFetch('/books/' + bookId);
    const res = await apiFetch('/books/create', {
      method: 'POST',
      body: JSON.stringify({
        title: book.title,
        prompt: book.prompt,
        tags: book.tags || [],
        length: book.length || 'novel',
        review_max_turns: book.review_max_turns || 2,
      }),
    });
    // Delete the old failed book entry
    await apiFetch('/books/' + bookId, { method: 'DELETE' });
    toast('New book queued!', 'success');
    closeModal();
    loadBooks();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
}

/* ── Delete Book ───────────────────────────────────────────────── */
async function deleteBook(bookId, title) {
  if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
  try {
    await apiFetch('/books/' + bookId, { method: 'DELETE' });
    toast('Book deleted.', 'success');
    closeModal();
    loadBooks();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
}

/* ── Init ──────────────────────────────────────────────────────── */
function initApp() {
  initTags();
  initCreateForm();
  initModal();
  // loadBooks runs after config check in initSettings → checkConfig
}
