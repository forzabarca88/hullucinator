# PLAN.md — Text-to-Speech for Hullucinator

## Objective

Add browser-based TTS playback for completed books using `kokoro-js` (self-hosted). Users can listen to books chapter-by-chapter with Play/Stop/Next Chapter controls. Playback progress persists across sessions via `localStorage`.

Uses `kokoro-js@1.2.1` — an 82M-parameter open-weight TTS model with 28 built-in voices (American and British English). Runs ONNX/WASM inference in a Web Worker, plays audio sequentially through `AudioContext`.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                           │
│  - COOP/COEP headers for SharedArrayBuffer                   │
│  - GET /api/books/{id}/tts-text → chapter plain text         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Frontend (vanilla JS, CSP: script-src 'self')               │
│                                                              │
│  static/js/vendor/kokoro.web.js — Self-hosted kokoro-js      │
│  static/js/tts-worker.js   — Web Worker (type: 'module')     │
│    - Kokoro model loading + ONNX/WASM inference              │
│  static/js/tts-manager.js  — Main thread                     │
│    - Chapter queue, sentence splitting, audio playback       │
│    - localStorage progress persistence                       │
└──────────────────────────────────────────────────────────────┘
```

### TTS Design for Books

- **Offline playback** of completed/reviewed books (not live streaming)
- **Single voice** per book, user-selected from 28 Kokoro voices
- **Chapter-by-chapter** progression with Play / Stop / Next Chapter controls
- **Persistent progress** via `localStorage` — resumes where user left off across sessions
- **Graceful fallback** — TTS failure never blocks book reading

### Voice Pool (28 voices)

American English female: `af_alloy`, `af_aoede`, `af_bella`, `af_heart`, `af_jessica`, `af_kore`, `af_nicole`, `af_nova`, `af_river`, `af_sarah`, `af_sky`

American English male: `am_adam`, `am_echo`, `am_eric`, `am_fenrir`, `am_liam`, `am_michael`, `am_onyx`, `am_puck`, `am_santa`

British English female: `bf_alice`, `bf_emma`, `bf_isabella`, `bf_lily`

British English male: `bm_daniel`, `bm_fable`, `bm_george`, `bm_lewis`

---

## Implementation Steps

### Phase 1: Self-host kokoro-js ✅ DONE

**Problem:** The app's CSP (`script-src 'self'`) blocks loading scripts from external CDNs. kokoro-js must be served from the app's own static directory.

#### 1.1 Download kokoro-js bundle

Download the web bundle and place it in `static/js/vendor/kokoro.web.js`. The bundle includes `@huggingface/transformers` internally — no separate install needed.

```bash
cd /home/forza/ai_gen/hullucinator
mkdir -p static/js/vendor
curl -o static/js/vendor/kokoro.web.js \
  https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js
```

**File created:** `static/js/vendor/kokoro.web.js`

**CSP note:** Model weights (`onnx-community/Kokoro-82M-v1.0-ONNX`) are fetched from HuggingFace at runtime. This is a data fetch, not script execution. The CSP `default-src` directive needs to allow HTTPS origins — addressed in Phase 2. kokoro-js also uses dynamic blob imports for ONNX Runtime WASM, requiring `'unsafe-eval'`, `'wasm-unsafe-eval'`, and `blob:` in `script-src`.

### Phase 2: Add COOP/COEP Headers ✅ DONE

**Problem:** kokoro-js uses ONNX Runtime WASM with multi-threading, which requires `SharedArrayBuffer`. This is only available when the page has both COOP and COEP headers.

- **Without COOP/COEP:** Single-threaded WASM (~30s per sentence)
- **With COOP/COEP:** Multi-threaded WASM using all CPU cores (~1-2s per sentence)

**File:** `app/middleware.py`

In `SecurityHeadersMiddleware.dispatch()`, add these two headers:

```python
response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
response.headers["Cross-Origin-Embedder-Policy"] = "same-origin"
```

COEP uses `same-origin` (not `require-corp`) to allow Kokoro to fetch model weights from HuggingFace. This means SharedArrayBuffer is unavailable and ONNX WASM runs single-threaded — still functional, just slower per-sentence synthesis.

Also relax `default-src` to allow HTTPS fetches (for HuggingFace model downloads):

Change:
```python
"default-src 'self'; "
```
To:
```python
"default-src 'self' https:; "
```

kokoro-js uses dynamic blob imports for ONNX Runtime WASM, requiring `'unsafe-eval'`, `'wasm-unsafe-eval'`, and `blob:` in `script-src`.

**Verification:** `self.crossOriginIsolated` will be `false` since COEP is `same-origin`. Kokoro falls back to single-threaded WASM — still works, just slower.

### Phase 3: Create TTS Web Worker ✅ DONE

**File created:** `static/js/tts-worker.js`

Imports kokoro-js from the self-hosted bundle. Handles model loading and sentence synthesis. Uses standard `generate()` (not streaming) — stable and fast enough for chapter playback (~200ms per sentence).

Key messages:
- Receives: `{ type: 'init' }`, `{ type: 'generate', id, text, voice }`, `{ type: 'stop' }`
- Sends back: `{ type: 'ready' }`, `{ type: 'audio', id, wav: ArrayBuffer }`, `{ type: 'error' }`

Uses `q4` quantization (~43MB model download, ~2x faster than q8).

```javascript
import { KokoroTTS, env } from '../vendor/kokoro.web.js';

// Configure ONNX Runtime WASM multi-threading
if (env?.backends?.onnx?.wasm) {
  env.backends.onnx.wasm.numThreads = navigator.hardwareConcurrency || 4;
}

let kokoro = null;
let isInitialized = false;

self.onmessage = async (e) => {
  const { type, id, text, voice, modelId, dtype, device } = e.data;

  if (type === 'init') {
    try {
      kokoro = await KokoroTTS.from_pretrained(
        modelId || 'onnx-community/Kokoro-82M-v1.0-ONNX',
        { dtype: dtype || 'q4', device: device || 'wasm' }
      );
      isInitialized = true;
      self.postMessage({ type: 'ready', device: kokoro.device, dtype: kokoro.dtype });
    } catch (err) {
      self.postMessage({ type: 'initError', message: err.message || String(err) });
    }
    return;
  }

  if (type === 'stop') {
    kokoro = null;
    isInitialized = false;
    return;
  }

  if (type === 'generate') {
    if (!isInitialized || !kokoro) {
      self.postMessage({ type: 'error', id, message: 'TTS not initialized' });
      return;
    }
    try {
      const rawAudio = await kokoro.generate(text, { voice });
      const wavBuffer = rawAudio.toWav();
      self.postMessage(
        { type: 'audio', id, wav: wavBuffer, sampleRate: rawAudio.sampling_rate },
        [wavBuffer]
      );
    } catch (err) {
      self.postMessage({ type: 'error', id, message: err.message || String(err) });
    }
  }
};
```

### Phase 4: Create TTS Manager (Main Thread) ✅ DONE

**File created:** `static/js/tts-manager.js`

`BookTTSManager` class handles chapter playback, sentence splitting, audio queue management, and progress persistence.

#### State

- `worker` — Web Worker reference (lazy-created on first use)
- `audioContext` — Web Audio API context
- `isInitialized` — Kokoro model loaded flag
- `voice` — Single voice ID for current playback session
- `bookId` — Current book being played
- `audioQueue` — Decoded AudioBuffers awaiting playback
- `sentenceQueue` — Sentences awaiting worker synthesis
- `_isPlaying` — Whether audio is currently playing
- `_workerBusy` — Whether worker is synthesizing
- `_activeId` — Current generation request ID (discards stale results on stop)

#### Key Methods

```javascript
class BookTTSManager {
  constructor() { /* init state, voice pool */ }

  // Load Kokoro model in worker (lazy, on first play)
  async initialize()

  // Play a specific chapter by 0-based index
  async playChapter(bookId, chapterIndex, voice)
    // 1. Ensure initialized
    // 2. Fetch chapter text: GET /api/books/{bookId}/tts-text?chapter={index}
    // 3. Strip markdown, split into sentences
    // 4. Queue sentences for worker synthesis
    // 5. Start audio playback pipeline
    // 6. Save progress to localStorage

  // Stop all playback, clear queues
  stop()

  // Clean up worker
  destroy()

  // Persist: { lastChapterIndex, lastSentenceIndex, voice }
  saveProgress(bookId, chapterIndex, sentenceIndex, voice)
  loadProgress(bookId)

  // Getters
  get isPlaying()
  get isIdle()
}
```

#### Sentence Splitting

Regex extracts complete sentences at `.`, `!`, `?`, `\n` boundaries. Markdown stripped before synthesis for cleaner speech output. Buffer capped at 5000 chars to prevent memory leaks.

#### Audio Pipeline

1. Worker synthesizes sentence → returns WAV ArrayBuffer
2. Main thread decodes via `AudioContext.decodeAudioData()` → AudioBuffer
3. AudioBuffer enqueued for playback
4. `_playNextInQueue()` plays sequentially via `AudioBufferSourceNode`
5. On `onended`, plays next buffer in queue

**Pipelined synthesis:** Worker synthesizes next sentence while previous one plays, ensuring gapless audio.

#### Global API

```javascript
const bookTTS = new BookTTSManager();
window.bookTTS = bookTTS;
```

### Phase 5: Backend — TTS Text Endpoint ✅ DONE

**File:** `app/routes.py`

**Note:** Markdown stripping order matters — code fences are processed before inline code to avoid orphaned backticks.

Add endpoint to serve chapter text as plain text (markdown stripped) for TTS consumption:

```python
@router.get("/api/books/{book_id}/tts-text")
async def get_book_tts_text(book_id: str, chapter: int = 0):
    """Get plain text of a chapter for TTS playback.

    Returns chapter content with markdown formatting stripped,
    optimized for text-to-speech synthesis.

    Args:
        book_id: Book UUID
        chapter: 0-based chapter index (defaults to 0)
    """
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    if not book_state.chapters:
        raise HTTPException(status_code=400, detail="Book has no chapters")

    chapter_titles = list(book_state.chapters.keys())
    if chapter < 0 or chapter >= len(chapter_titles):
        raise HTTPException(
            status_code=400,
            detail=f"Chapter index {chapter} out of range (0-{len(chapter_titles) - 1})"
        )

    title = chapter_titles[chapter]
    content = book_state.chapters[title]

    # Strip markdown for cleaner speech
    plain_text = content
    plain_text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', plain_text)
    plain_text = re.sub(r'\*\*(.+?)\*\*', r'\1', plain_text)
    plain_text = re.sub(r'\*(.+?)\*', r'\1', plain_text)
    plain_text = re.sub(r'`[^`]+`', '', plain_text)
    plain_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', plain_text)
    plain_text = re.sub(r'#{1,6}\s*', '', plain_text)
    plain_text = re.sub(r'^[-*+]\s+', '', plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r'^\d+[.)]\s+', '', plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r'^>\s+', '', plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r'```[\s\S]*?```', '', plain_text)
    plain_text = re.sub(r'^---+$', '', plain_text, flags=re.MULTILINE)

    return {
        "title": title,
        "text": plain_text.strip(),
        "chapter_index": chapter,
        "total_chapters": len(chapter_titles)
    }
```

### Phase 6: UI Integration — Playback Controls in Detail Modal ✅ DONE

#### 6.1 CSS Styles ✅ DONE

**File:** `static/css/styles.css` — Add TTS control styles matching hullucinator's design system (teal accents, Playfair Display headings, Source Sans 3 body, IBM Plex Mono data):

```css
/* ═══════════════════════════════════════════════════════════════
   17. TTS Playback Controls
   ═══════════════════════════════════════════════════════════════ */
.tts-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: var(--teal-light);
  border: 1px solid rgba(27,107,97,0.2);
  margin-bottom: 1rem;
}

.tts-controls .tts-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: transparent;
  border: 1px solid var(--vellum);
  color: var(--ink);
  font-family: var(--body-font);
  font-size: 12px;
  font-weight: 500;
  padding: 0.35rem 0.7rem;
  cursor: pointer;
  transition: all 0.2s;
}
.tts-controls .tts-btn:hover { border-color: var(--teal); color: var(--teal); }
.tts-controls .tts-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.tts-controls .tts-btn.tts-btn-play {
  background: var(--teal);
  color: #fff;
  border-color: var(--teal);
}
.tts-controls .tts-btn.tts-btn-play:hover { background: #155a52; }

.tts-status {
  flex: 1;
  text-align: right;
  font-family: var(--data-font);
  font-size: 11px;
  color: var(--ash);
}

.tts-voice-select {
  padding: 0.3rem 0.5rem;
  background: var(--page);
  border: 1px solid var(--vellum);
  color: var(--ink);
  font-family: var(--body-font);
  font-size: 12px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%237A6F62'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.5rem center;
  padding-right: 1.5rem;
}

.tts-progress-bar {
  width: 100%;
  height: 3px;
  background: var(--vellum);
  margin-top: 0.5rem;
}
.tts-progress-fill {
  height: 100%;
  background: var(--teal);
  transition: width 0.3s ease;
}

.tts-loading {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--data-font);
  font-size: 11px;
  color: var(--brass);
}
.tts-loading .spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--vellum);
  border-top-color: var(--teal);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
```

#### 6.2 HTML — Add TTS Controls to Detail Modal ✅ DONE

**File:** `static/js/renderers.js` — In `renderDetail()`, add a TTS playback section after the chapters section (before actions) for completed/reviewed books that have chapters:

```javascript
// TTS Playback Controls (for completed/reviewed books with chapters)
if (book.chapters && (book.status === 'completed' || book.status === 'reviewed')) {
  const entries = Object.entries(book.chapters);
  html += `<div class="modal-section">
    <h3>Play Book</h3>
    <div class="tts-controls" data-book-id="${book.id}">
      <select class="tts-voice-select" id="ttsVoiceSelect" title="Select voice">
        ${bookTTS?.VOICE_POOL?.map(v => `<option value="${v}">${v}</option>`).join('')}
      </select>
      <button class="tts-btn tts-btn-play" data-tts-action="play" title="Play from beginning">▶ Play</button>
      <button class="tts-btn" data-tts-action="resume" title="Resume from last position">↻ Resume</button>
      <button class="tts-btn" data-tts-action="stop" title="Stop playback">■ Stop</button>
      <button class="tts-btn" data-tts-action="next" title="Play next chapter">⏭ Next</button>
      <div class="tts-status" id="ttsStatus">Ready</div>
    </div>
    <div class="tts-progress-bar"><div class="tts-progress-fill" id="ttsProgressFill" style="width:0%"></div></div>
  </div>`;
}
```

#### 6.3 Wire Up Event Listeners ✅ DONE

**File:** `static/js/app.js` — In `attachModalActionListeners(bookId)`, add TTS control event listeners after the existing `button[data-action]` handlers:

```javascript
// TTS playback controls
const ttsControls = $('detailContent').querySelector('.tts-controls');
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
```

Also in `closeModal()`: stop TTS playback when modal closes:

```javascript
function closeModal() {
  $('detailOverlay').classList.remove('active');
  stopPolling();
  bookTTS.stop();
  currentBookId = null;
}
```

#### 6.4 Script Loading Order ✅ DONE

**File:** `static/index.html` — Insert `tts-manager.js` between `renderers.js` and `app.js`:

```html
<script src="/static/js/config.js"></script>
<script src="/static/js/ui.js"></script>
<script src="/static/js/renderers.js"></script>
<script src="/static/js/tts-manager.js"></script>
<script src="/static/js/app.js"></script>
<script src="/static/js/settings.js"></script>
<script src="/static/js/boot.js"></script>
```

### Phase 7: Graceful Fallback ✅ DONE

TTS is optional. If initialization fails (no SharedArrayBuffer, model download fails, worker error), the UI degrades gracefully:

- Toast notification: "TTS unavailable — check console for details"
- Play/Resume buttons show disabled state
- Book reading proceeds normally without audio
- No blocking of core functionality

**Implementation in `BookTTSManager.initialize()`:**

```javascript
async initialize() {
  if (this.isInitialized) return true;
  if (this._initFailed) return false;

  try {
    if (typeof SharedArrayBuffer === 'undefined') {
      console.warn('[TTS] SharedArrayBuffer not available — single-threaded WASM will be slow.');
    }

    this.worker = new Worker('/static/js/tts-worker.js', { type: 'module' });
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.worker.removeEventListener('message', onInit);
        reject(new Error('TTS initialization timed out after 120s'));
      }, 120000);

      const onInit = (e) => {
        if (e.data.type === 'ready') {
          this.worker.removeEventListener('message', onInit);
          clearTimeout(timeout);
          this.isInitialized = true;
          resolve();
        } else if (e.data.type === 'initError') {
          this.worker.removeEventListener('message', onInit);
          clearTimeout(timeout);
          reject(new Error(e.data.message));
        }
      };

      this.worker.addEventListener('message', onInit);
      this.worker.postMessage({
        type: 'init',
        modelId: 'onnx-community/Kokoro-82M-v1.0-ONNX',
        dtype: 'q4',
        device: 'wasm',
      });
    });

    return true;
  } catch (error) {
    console.error('[TTS] Initialization failed:', error);
    this._initFailed = true;
    this.destroy();
    return false;
  }
}
```

---

## File Summary

| File | Action | Purpose |
|------|--------|---------|
| `static/js/vendor/kokoro.web.js` | **Create** | Self-hosted kokoro-js bundle |
| `static/js/tts-worker.js` | **Create** | Web Worker for Kokoro inference |
| `static/js/tts-manager.js` | **Create** | Main-thread TTS manager class |
| `app/middleware.py` | **Modify** | Add COOP/COEP headers, relax CSP `default-src` |
| `app/routes.py` | **Modify** | Add `GET /api/books/{id}/tts-text` endpoint |
| `static/js/renderers.js` | **Modify** | Add TTS controls section to `renderDetail()` |
| `static/js/app.js` | **Modify** | Wire TTS event listeners; stop TTS on modal close |
| `static/css/styles.css` | **Modify** | Add TTS control styles |
| `static/index.html` | **Modify** | Add `tts-manager.js` to script loading order |

---

## Testing Checklist

### Automated (✅ PASSING — 185 tests)
- [x] COOP/COEP headers present in response
- [x] CSP `default-src` allows HTTPS, `script-src` includes `'unsafe-eval'`, `'wasm-unsafe-eval'`, and `blob:` for TTS WASM
- [x] TTS text endpoint returns 404 for unknown book
- [x] TTS text endpoint returns 400 when book has no chapters
- [x] TTS text endpoint strips all markdown (bold, italic, code, links, headings, lists, blockquotes, fences)
- [x] TTS text endpoint returns correct chapter by index
- [x] TTS text endpoint returns 400 for out-of-range chapter
- [x] `tts-manager.js` included in index.html script loading order
- [x] Full test suite passes: `.venv/bin/pytest -x -q`

### Manual (requires browser)
- [ ] kokoro-js bundle loads from `/static/js/vendor/kokoro.web.js` without CSP violations
- [ ] `self.crossOriginIsolated === true` in browser console
- [ ] Model downloads from HuggingFace on first TTS use (~43MB with q4)
- [ ] Worker synthesizes a sentence and returns valid WAV audio
- [ ] Audio plays through AudioContext without errors
- [ ] Play button starts chapter 1, Next advances to next chapter
- [ ] Stop button halts playback and clears queues
- [ ] Resume button continues from saved position
- [ ] Progress persists across page reloads (localStorage)
- [ ] Voice selector changes voice for subsequent chapters
- [ ] Progress bar shows chapter completion percentage
- [ ] TTS controls only appear for completed/reviewed books with chapters
- [ ] Graceful fallback: TTS failure doesn't break book reading
- [ ] Works in Chrome, Firefox, Safari
- [ ] No CSP violations in browser console

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| kokoro-js bundle changes break self-hosted copy | Model fails to load | Pin exact version (1.2.1). Bundle includes transformers internally. |
| HuggingFace blocks browser fetches | Model can't download | CSP `default-src 'self' https:` allows HTTPS fetches. HF doesn't block browser fetches. |
| SharedArrayBuffer unavailable (Safari, some configs) | Slow single-threaded WASM | Document expected performance. First use is slowest (model download). |
| Large model download (~43MB) | Slow first playback | Progressive loading indicator. Model caches in browser after first download. |
| Memory pressure from long chapters | OOM on low-end devices | Sentence-by-sentence synthesis. Audio buffers released after playback. |
| CSP violation from worker module import | Worker fails to load | Worker uses `{ type: 'module' }` with relative import to self-hosted bundle. CSP `script-src` includes `'unsafe-eval'`, `'wasm-unsafe-eval'`, and `blob:` for kokoro-js blob imports. |
