/* ── Settings Panel & Setup Wizard ─────────────────────────────────── */

let appConfigured = false;

function initSettings() {
  $('settingsBtn').addEventListener('click', () => {
    $('settingsPanel').classList.add('active');
    $('settingsOverlay').classList.add('active');
    loadConfig();
  });
  $('settingsClose').addEventListener('click', closeSettings);
  $('settingsOverlay').addEventListener('click', closeSettings);

  $('saveConfigBtn').addEventListener('click', saveConfig);

  // Writer fetch button
  $('fetchWriterModelsBtn').addEventListener('click', () => fetchModels('writer', 'cfgWriterModel'));

  // Reviewer fetch button (settings panel)
  $('fetchReviewerModelsBtn').addEventListener('click', () => fetchModels('reviewer', 'cfgReviewerModel'));

  // Setup wizard buttons
  $('setupSaveBtn').addEventListener('click', saveSetupConfig);
  $('fetchSetupModelsBtn').addEventListener('click', () => fetchModels('writer', 'setupModel'));
  $('fetchSetupReviewerModelsBtn').addEventListener('click', () => fetchModels('reviewer', 'setupReviewerModel'));

  // On page load, check if configured
  checkConfig();
}

async function checkConfig() {
  try {
    const cfg = await apiFetch('/config');
    appConfigured = cfg.configured;

    // Sync the create form's Max Review Turns to match saved config
    if ($('maxTurns')) $('maxTurns').value = cfg.review_max_turns || 2;

    if (!appConfigured) {
      // Show setup wizard, hide main content
      $('setupOverlay').classList.add('active');
      $('mainContent').style.display = 'none';
      $('header').style.display = 'none';
      // Pre-fill from persisted config if partial
      $('setupEndpoint').value = cfg.endpoint_url || '';
      $('setupModel').value = cfg.model_name || '';
      $('setupReviewerEndpoint').value = cfg.reviewer_endpoint_url || '';
      $('setupReviewerApiKey').value = '';  // never display saved key
      $('setupReviewerModel').value = cfg.reviewer_model_name || '';
      $('setupMaxTurns').value = cfg.review_max_turns || 2;
      $('setupWordThreshold').value = cfg.review_word_threshold || 30000;
      $('setupChunkSize').value = cfg.review_chunk_size || 5;
    } else {
      // Already configured — populate settings panel fields
      $('cfgEndpoint').value = cfg.endpoint_url || '';
      $('cfgWriterModel').value = cfg.model_name || '';
      $('cfgReviewerEndpoint').value = cfg.reviewer_endpoint_url || '';
      $('cfgReviewerModel').value = cfg.reviewer_model_name || '';
      $('cfgMaxTurns').value = cfg.review_max_turns || 2;
      $('cfgWordThreshold').value = cfg.review_word_threshold || 30000;
      $('cfgChunkSize').value = cfg.review_chunk_size || 5;
      // Load the library of existing books
      loadBooks();
    }
  } catch (err) {
    console.error('checkConfig error:', err);
    // If config endpoint fails, assume not configured
    $('setupOverlay').classList.add('active');
    $('mainContent').style.display = 'none';
    $('header').style.display = 'none';
  }
}

function closeSettings() {
  $('settingsPanel').classList.remove('active');
  $('settingsOverlay').classList.remove('active');
}

/* ── Settings Panel (slide-out, for already-configured users) ─── */

async function loadConfig() {
  try {
    const cfg = await apiFetch('/config');
    $('cfgEndpoint').value = cfg.endpoint_url || '';
    $('cfgWriterModel').value = cfg.model_name || '';
    $('cfgApiKey').value = '';  // never display saved key
    $('cfgReviewerEndpoint').value = cfg.reviewer_endpoint_url || '';
    $('cfgReviewerApiKey').value = '';  // never display saved key
    $('cfgReviewerModel').value = cfg.reviewer_model_name || '';
    $('cfgMaxTurns').value = cfg.review_max_turns || 2;
    $('cfgWordThreshold').value = cfg.review_word_threshold || 30000;
    $('cfgChunkSize').value = cfg.review_chunk_size || 5;
  } catch (err) {
    console.error('loadConfig error:', err);
  }
}

async function saveConfig() {
  try {
    // (M7 fix: send empty string "" instead of null for cleared fields
    // so the server can properly clear persisted values)
    const cfg = {
      endpoint_url: $('cfgEndpoint').value.trim() || '',
      model_name: $('cfgWriterModel').value.trim() || '',
      api_key: $('cfgApiKey').value.trim() || '',
      reviewer_endpoint_url: $('cfgReviewerEndpoint').value.trim() || '',
      reviewer_api_key: $('cfgReviewerApiKey').value.trim() || '',
      reviewer_model_name: $('cfgReviewerModel').value.trim() || '',
      review_max_turns: parseInt($('cfgMaxTurns').value),
      review_word_threshold: parseInt($('cfgWordThreshold').value),
      review_chunk_size: parseInt($('cfgChunkSize').value),
    };
    const res = await apiFetch('/config', { method: 'POST', body: JSON.stringify(cfg) });
    toast('Configuration saved!', 'success');
    closeSettings();
    // Update configured state
    appConfigured = res.config.configured;
    // Sync create form's Max Review Turns with saved config
    if ($('maxTurns')) $('maxTurns').value = res.config.review_max_turns || 2;
  } catch (err) {
    toast('Save error: ' + err.message, 'error');
  }
}

/* ── Setup Wizard (first-time configuration) ───────────────────── */

async function saveSetupConfig() {
  const endpoint = $('setupEndpoint').value.trim();
  const model = $('setupModel').value.trim();
  const apiKey = $('setupApiKey').value.trim();

  if (!endpoint) {
    toast('Endpoint URL is required.', 'error');
    $('setupEndpoint').focus();
    return;
  }
  if (!model) {
    toast('Model name is required.', 'error');
    $('setupModel').focus();
    return;
  }

  const cfg = {
    endpoint_url: endpoint,
    model_name: model,
    api_key: apiKey || null,
    reviewer_endpoint_url: $('setupReviewerEndpoint').value.trim() || null,
    reviewer_api_key: $('setupReviewerApiKey').value.trim() || null,
    reviewer_model_name: $('setupReviewerModel').value.trim() || null,
    review_max_turns: parseInt($('setupMaxTurns').value),
    review_word_threshold: parseInt($('setupWordThreshold').value),
    review_chunk_size: parseInt($('setupChunkSize').value),
  };

  try {
    const res = await apiFetch('/config', { method: 'POST', body: JSON.stringify(cfg) });
    toast('Configuration saved! You can now generate books.', 'success');

    // Transition from setup to main app
    appConfigured = res.config.configured;
    $('setupOverlay').classList.remove('active');
    $('mainContent').style.display = '';
    $('header').style.display = '';

    // Sync settings panel and create form with saved config
    $('cfgEndpoint').value = res.config.endpoint_url || '';
    $('cfgWriterModel').value = res.config.model_name || '';
    $('cfgReviewerEndpoint').value = res.config.reviewer_endpoint_url || '';
    $('cfgReviewerModel').value = res.config.reviewer_model_name || '';
    $('cfgMaxTurns').value = res.config.review_max_turns || 2;
    $('cfgWordThreshold').value = res.config.review_word_threshold || 30000;
    $('cfgChunkSize').value = res.config.review_chunk_size || 5;
    if ($('maxTurns')) $('maxTurns').value = res.config.review_max_turns || 2;

    // Load existing books
    loadBooks();
  } catch (err) {
    toast('Save error: ' + err.message, 'error');
  }
}

/* ── Model Fetching (shared by setup wizard and settings panel) ─ */

async function fetchModels(role, inputId) {
  const input = $(inputId);
  if (!input) return;

  const endpoint = role === 'reviewer' ? '/reviewer/models' : '/models';
  const isSetup = inputId.startsWith('setup');

  const fetchBtn = role === 'reviewer'
    ? (inputId === 'cfgReviewerModel' ? $('fetchReviewerModelsBtn') : $('fetchSetupReviewerModelsBtn'))
    : (inputId === 'cfgWriterModel' ? $('fetchWriterModelsBtn') : $('fetchSetupModelsBtn'));

  let fetchUrl = endpoint;
  if (isSetup) {
    const epField = role === 'reviewer' ? $('setupReviewerEndpoint') : $('setupEndpoint');
    const ep = epField ? epField.value.trim() : null;
    if (ep) {
      fetchUrl += '?endpoint_url=' + encodeURIComponent(ep);
      const key = role === 'reviewer'
        ? ($('setupReviewerApiKey') ? $('setupReviewerApiKey').value.trim() : null)
        : ($('setupApiKey') ? $('setupApiKey').value.trim() : null);
      if (key) fetchUrl += '&api_key=' + encodeURIComponent(key);
    } else if (role === 'reviewer') {
      // No reviewer endpoint — use writer's endpoint for fetching
      const writerEp = $('setupEndpoint') ? $('setupEndpoint').value.trim() : null;
      if (writerEp) {
        fetchUrl = '/models?endpoint_url=' + encodeURIComponent(writerEp);
        const key = $('setupApiKey') ? $('setupApiKey').value.trim() : null;
        if (key) fetchUrl += '&api_key=' + encodeURIComponent(key);
      }
    }
  } else {
    // Settings panel: pass current field values so the server uses
    // the endpoint/key the user just typed (not the persisted config).
    const epField = role === 'reviewer' ? $('cfgReviewerEndpoint') : $('cfgEndpoint');
    const ep = epField ? epField.value.trim() : null;
    const apiKey = role === 'reviewer'
      ? ($('cfgReviewerApiKey') ? $('cfgReviewerApiKey').value.trim() : null)
      : ($('cfgApiKey') ? $('cfgApiKey').value.trim() : null);

    if (ep) {
      fetchUrl += '?endpoint_url=' + encodeURIComponent(ep);
      if (apiKey) fetchUrl += '&api_key=' + encodeURIComponent(apiKey);
    } else if (role === 'reviewer') {
      // No reviewer endpoint set — fall back to writer's endpoint
      const writerEp = $('cfgEndpoint') ? $('cfgEndpoint').value.trim() : null;
      if (writerEp) {
        fetchUrl = '/models?endpoint_url=' + encodeURIComponent(writerEp);
        const writerKey = $('cfgApiKey') ? $('cfgApiKey').value.trim() : null;
        if (writerKey) fetchUrl += '&api_key=' + encodeURIComponent(writerKey);
      }
    }
  }

  const icon = fetchBtn.querySelector('.fetch-icon');
  if (icon) icon.classList.add('spinning');
  fetchBtn.disabled = true;

  try {
    const res = await apiFetch(fetchUrl);
    const models = res.models || [];
    const priorValue = input.value.trim();

    if (models.length) {
      const listId = inputId + 'List';
      let listEl = $(listId);

      if (!listEl) {
        listEl = document.createElement('div');
        listEl.className = 'model-list';
        listEl.id = listId;
        const fieldContainer = input.closest('.field');
        if (fieldContainer) {
          fieldContainer.appendChild(listEl);
        } else {
          input.parentElement.appendChild(listEl);
        }
      }

      listEl.style.display = 'block';
      listEl.innerHTML = '';

      for (const m of models) {
        const item = document.createElement('div');
        item.className = 'model-list-item' + (m.id === (res.current_model || '') ? ' current' : '');
        item.textContent = m.id + (m.id === (res.current_model || '') ? ' ← current' : '');
        item.addEventListener('click', () => {
          input.value = m.id;
          listEl.style.display = 'none';
        });
        listEl.appendChild(item);
      }

      // Only auto-fill and hide the list if the input was empty.
      // If the user already had a value, they clicked Fetch to see
      // available options — keep the list visible.
      if (!priorValue && res.current_model && models.some(m => m.id === res.current_model)) {
        input.value = res.current_model;
        listEl.style.display = 'none';
      }

      toast(`Found ${models.length} models`, 'success');
    } else {
      if (res.uses_writer) {
        toast('No reviewer endpoint set. Using writer endpoint to fetch models instead.', 'info');
      } else {
        toast('No models found. Check endpoint URL.', 'error');
      }
    }
  } catch (err) {
    console.error('fetchModels error:', err);
    toast('Model fetch failed: ' + err.message, 'error');
  } finally {
    if (icon) icon.classList.remove('spinning');
    fetchBtn.disabled = false;
  }
}
