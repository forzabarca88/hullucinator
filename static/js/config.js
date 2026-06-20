/* ── Shared Config — loaded from server, single source of truth ─── */

let SHARED_CONFIG = null;

async function loadSharedConfig() {
  if (SHARED_CONFIG) return SHARED_CONFIG;
  SHARED_CONFIG = await apiFetch('/config-schema');
  return SHARED_CONFIG;
}

/* ── Renderer helpers ──────────────────────────────────────────── */

function renderLengthSelect(selectEl) {
  if (!SHARED_CONFIG || !selectEl) return;
  selectEl.innerHTML = SHARED_CONFIG.lengths.map(l =>
    `<option value="${l.key}">${l.label} (${l.chapter_range} chapters, ${l.word_range} words)</option>`
  ).join('');
}

function renderMaxTurnsSelect(selectEl) {
  if (!SHARED_CONFIG || !selectEl) return;
  selectEl.innerHTML = SHARED_CONFIG.review.turn_options.map(o =>
    `<option value="${o.value}" ${o.value === SHARED_CONFIG.review.max_turns_default ? 'selected' : ''}>${o.label}</option>`
  ).join('');
}

function getStatusLabel(status) {
  if (!SHARED_CONFIG) return status.replace(/_/g, ' ');
  const s = SHARED_CONFIG.statuses.find(st => st.key === status);
  return s ? s.label : status.replace(/_/g, ' ');
}

function getStatusCssClass(status) {
  if (!SHARED_CONFIG) return `status-${status}`;
  const s = SHARED_CONFIG.statuses.find(st => st.key === status);
  return s ? s.css_class : `status-${status}`;
}

function isTerminalStatus(status) {
  if (!SHARED_CONFIG) return ['completed', 'reviewed', 'failed'].includes(status);
  const s = SHARED_CONFIG.statuses.find(st => st.key === status);
  return s ? s.is_terminal : false;
}

function isActiveStatus(status) {
  if (!SHARED_CONFIG) return ['pending', 'summary_generated', 'outline_generated', 'in_progress', 'reviewing'].includes(status);
  const s = SHARED_CONFIG.statuses.find(st => st.key === status);
  return s ? s.is_active : false;
}
