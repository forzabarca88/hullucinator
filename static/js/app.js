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
      counterEl.className = 'field-hint' + (len > (SHARED_CONFIG?.ui?.prompt_warn_threshold ?? 10000) ? ' prompt-warn' : '');
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

    const hasActive = books.some(b => isActiveStatus(b.status));

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

  // TTS playback controls
  const ttsControls = detailContent.querySelector('.tts-controls');
  if (ttsControls) {
    const voiceSelect = $('ttsVoiceSelect');
    const ttsStatus = $('ttsStatus');
    const ttsProgressFill = $('ttsProgressFill');

    // Restore saved voice preference
    const progress = bookTTS.loadProgress(bookId);
    if (progress && voiceSelect) {
      voiceSelect.value = progress.voice || bookTTS.VOICE_POOL[0];
    }

    ttsControls.querySelectorAll('[data-tts-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.ttsAction;
        const voice = voiceSelect?.value || bookTTS.VOICE_POOL[0];

        if (action === 'play') {
          ttsStatus.textContent = 'Initializing...';
          const ok = await bookTTS.initialize();
          if (!ok) { ttsStatus.textContent = 'TTS unavailable'; return; }
          await bookTTS.playChapter(bookId, 0, voice);
        } else if (action === 'resume') {
          const saved = bookTTS.loadProgress(bookId);
          if (!saved) { toast('No saved progress to resume.', 'info'); return; }
          ttsStatus.textContent = 'Initializing...';
          const ok = await bookTTS.initialize();
          if (!ok) { ttsStatus.textContent = 'TTS unavailable'; return; }
          await bookTTS.playChapter(bookId, saved.lastChapterIndex, saved.voice);
        } else if (action === 'stop') {
          bookTTS.stop();
          ttsStatus.textContent = 'Stopped';
          if (ttsProgressFill) ttsProgressFill.style.width = '0%';
        } else if (action === 'next') {
          const saved = bookTTS.loadProgress(bookId);
          if (saved) {
            await bookTTS.playChapter(bookId, saved.lastChapterIndex + 1, saved.voice);
          }
        }
      });
    });

    // Update status display during playback
    bookTTS._onStatusChange = (status, chapterIndex, totalChapters) => {
      if (ttsStatus) ttsStatus.textContent = status;
      if (ttsProgressFill) {
        const pct = totalChapters > 0 ? ((chapterIndex + 1) / totalChapters * 100) : 0;
        ttsProgressFill.style.width = pct + '%';
      }
    };
  }
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
    if (isActiveStatus(book.status)) {
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
    const res = await apiFetch('/books/' + bookId + '/retry', { method: 'POST' });
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
    await bookTTS.clearCache(bookId);
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
  renderLengthSelect($('bookLength'));
  renderMaxTurnsSelect($('maxTurns'));
  initCreateForm();
  initModal();
  // loadBooks runs after config check in initSettings → checkConfig
}
