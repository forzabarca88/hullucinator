/**
 * UI rendering utilities — generates HTML fragments for the book library
 * and detail modal.
 *
 * Depends on: config.js (SHARED_CONFIG, getStatusLabel, getStatusCssClass),
 *             ui.js (esc, renderMarkdown)
 * Used by: app.js (buildBookCardHtml, renderDetail, buildReviewSection)
 */

/* ── Status Badge ──────────────────────────────────────────────── */
function statusBadge(status) {
  return `<span class="${getStatusCssClass(status)}">${getStatusLabel(status)}</span>`;
}

/* ── Book Card Renderer ────────────────────────────────────────── */
function buildBookCardHtml(b, p, pct, isDone, isFail, pClass) {
  let tagsHtml = (b.tags || []).map(t => `<span class="tag-badge">${esc(t)}</span>`).join('');
  let lengthLabel = b.length ? getStatusLabel(b.length) : '';
  let lengthBadge = lengthLabel ? `<span class="status-label" style="color:var(--status-pending);background:rgba(91,123,138,0.08)">${esc(lengthLabel)}</span>` : '';

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

/* ── Detail Modal Renderer ─────────────────────────────────────── */
function renderDetail(book) {
  let html = '';

  // Settings used when creating this book
  html += `<div class="modal-section">
    <h3>Settings</h3>
    <div class="detail-settings">
      <div class="detail-setting"><span class="detail-label">Prompt</span><div class="detail-value">${esc(book.prompt)}</div></div>
      <div class="detail-setting"><span class="detail-label">Length</span><div class="detail-value">${esc(getStatusLabel(book.length || 'novel'))}</div></div>
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
    html += `<div class="modal-section"><h3>Summary</h3><div class="markdown-body">${renderMarkdown(book.summary)}</div></div>`;
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
        <div class="markdown-body">${renderMarkdown(content)}</div></details>`;
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
  if (book.status === 'failed' || book.status === 'completed' || book.status === 'reviewed') {
    html += `<button class="btn btn-secondary btn-sm" data-action="retry">Retry</button>`;
  }
  html += `<button class="btn btn-secondary btn-sm" data-action="delete" style="color:var(--status-error);border-color:var(--status-error)">Delete</button>`;
  html += `</div>`;

  return html;
}

/* ── Review Section Renderer ───────────────────────────────────── */
function buildReviewSection(review, history) {
  let html = `<div class="review-section">`;
  html += `<h3>Review Results</h3>`;

  const score = review.overall_score ?? 0;
  const verdict = review.verdict || 'unknown';
  const passScore = SHARED_CONFIG?.review?.pass_score ?? 7;
  const failScore = SHARED_CONFIG?.review?.fail_score ?? 4;
  const scoreClass = score >= passScore ? 'good' : score >= failScore ? 'ok' : 'bad';
  const passClass = verdict === 'ready' ? 'passed' : 'failed';

  html += `<div class="review-score ${scoreClass}">${score}/10</div>`;
  html += `<div class="review-verdict ${passClass}">${verdict === 'ready' ? 'Approved' : 'Needs Revision'}</div>`;

  if (review.max_turns_reached) {
    html += `<p style="color:var(--brass);text-align:center;font-size:0.85rem;margin-bottom:0.5rem">
      Max turns reached — some issues may remain</p>`;
  }

  // Build turn-by-turn critique and corrections view
  const turns = history && history.length > 0 ? history : [review];

  if (turns.length > 0) {
    html += `<details style="margin-top:0.5rem"><summary style="cursor:pointer;font-family:var(--body-font);color:var(--ash);font-size:0.85rem;font-weight:500">View Full Critique</summary>`;

    for (const turn of turns) {
      const tNum = turn.turn;
      html += `<div class="critique-turn">`;
      html += `<div class="critique-turn-header">Turn ${tNum}</div>`;

      // Critique text (rendered as markdown)
      if (turn.critique) {
        html += `<div class="review-critique markdown-body">${renderMarkdown(turn.critique)}</div>`;
      }

      // Issues found in this turn
      if (turn.issues && turn.issues.length) {
        html += `<div class="critique-issues"><strong>Issues (${turn.issues.length}):</strong>`;
        for (const issue of turn.issues) {
          html += `<div class="critique-issue">
            <span class="corr-chapter">${esc(issue.chapter || 'unknown')}</span>
            <span class="corr-type">[${esc(issue.type || 'general')}]</span>
            <div class="issue-description">${esc(issue.description || '')}</div>
            ${issue.suggestion ? `<div class="issue-suggestion">Suggestion: ${esc(issue.suggestion)}</div>` : ''}
          </div>`;
        }
        html += `</div>`;
      }

      // Corrections applied in this turn
      if (turn.corrections && turn.corrections.length) {
        html += `<div class="critique-corrections"><strong>Corrections (${turn.corrections.length}):</strong>`;
        for (const c of turn.corrections) {
          html += `<div class="correction-item">
            <span class="corr-chapter">${esc(c.chapter)}</span>
            <span class="corr-type">[${esc(c.issue_type)}]</span>
            <div style="margin-top:0.2rem;font-size:0.8rem;color:var(--ash)">${esc(c.issue_description)}</div>
          </div>`;
        }
        html += `</div>`;
      }

      html += `</div>`;
    }

    html += `</details>`;
  }

  html += `</div>`;
  return html;
}
