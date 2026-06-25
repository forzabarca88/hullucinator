/**
 * TTS Manager — Main thread controller for browser-based book playback.
 *
 * Handles chapter playback, sentence splitting, audio queue management,
 * and progress persistence via localStorage.
 *
 * API:
 *   bookTTS.initialize()        — Load Kokoro model (lazy, on first use)
 *   bookTTS.playChapter(id, idx, voice) — Play a chapter by 0-based index
 *   bookTTS.stop()              — Stop all playback, clear queues
 *   bookTTS.destroy()           — Clean up worker
 *   bookTTS.saveProgress(...)   — Persist progress to localStorage
 *   bookTTS.loadProgress(id)    — Load saved progress
 *   bookTTS.isPlaying           — Whether audio is currently playing
 *   bookTTS.isIdle              — Whether system is idle (not playing, not busy)
 *   bookTTS.VOICE_POOL          — Array of available voice IDs
 */

const VOICE_POOL = [
  'af_alloy', 'af_aoede', 'af_bella', 'af_heart', 'af_jessica',
  'af_kore', 'af_nicole', 'af_nova', 'af_river', 'af_sarah', 'af_sky',
  'am_adam', 'am_echo', 'am_eric', 'am_fenrir', 'am_liam',
  'am_michael', 'am_onyx', 'am_puck', 'am_santa',
  'bf_alice', 'bf_emma', 'bf_isabella', 'bf_lily',
  'bm_daniel', 'bm_fable', 'bm_george', 'bm_lewis',
];

/** Strip markdown formatting for cleaner speech output. */
function stripMarkdown(text) {
  let t = text;
  t = t.replace(/\*\*\*(.+?)\*\*\*/g, '$1');
  t = t.replace(/\*\*(.+?)\*\*/g, '$1');
  t = t.replace(/\*(.+?)\*/g, '$1');
  t = t.replace(/`[^`]+`/g, '');
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  t = t.replace(/#{1,6}\s+/g, '');
  t = t.replace(/^[-*+]\s+/gm, '');
  t = t.replace(/^\d+[.)]\s+/gm, '');
  t = t.replace(/^>\s+/gm, '');
  t = t.replace(/```[\s\S]*?```/g, '');
  t = t.replace(/^---+$/gm, '');
  return t;
}

/** Split text into sentences at . ! ? \n boundaries. */
function splitSentences(text) {
  const raw = text.match(/[^.!?]+[.!?]|\n+/g);
  if (!raw) return [text];
  return raw
    .map(s => s.trim())
    .filter(s => s.length > 0)
    .map(s => s.replace(/\s+/g, ' '));
}

class BookTTSManager {
  constructor() {
    this.VOICE_POOL = VOICE_POOL;
    this.worker = null;
    this.audioContext = null;
    this.isInitialized = false;
    this._initFailed = false;
    this.voice = VOICE_POOL[0];
    this.bookId = null;
    this.audioQueue = [];
    this.sentenceQueue = [];
    this._isPlaying = false;
    this._workerBusy = false;
    this._activeId = 0;
    this._currentChapterIndex = 0;
    this._totalChapters = 0;
    this._onStatusChange = null;
  }

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
            this._setupWorkerListeners();
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

  _setupWorkerListeners() {
    this.worker.onmessage = (e) => {
      const data = e.data;

      if (data.type === 'audio') {
        this._workerBusy = false;
        // Discard stale results (from previous stop)
        if (data.id !== this._activeId) return;

        this.audioContext.decodeAudioData(data.wav, (buffer) => {
          this.audioQueue.push(buffer);
          if (!this._isPlaying) {
            this._playNextInQueue();
          }
          // Keep synthesizing next sentence while playing
          this._synthesizeNext();
        }, (err) => {
          console.error('[TTS] decodeAudioData failed:', err);
          this._synthesizeNext();
        });
      }

      if (data.type === 'error') {
        this._workerBusy = false;
        console.error('[TTS] Worker error:', data.message);
        this._synthesizeNext();
      }
    };
  }

  async playChapter(bookId, chapterIndex, voice) {
    if (!this.isInitialized) {
      const ok = await this.initialize();
      if (!ok) return false;
    }

    // Stop any current playback
    this._stopPlayback();

    this.bookId = bookId;
    this.voice = voice;

    // Fetch chapter text
    const resp = await fetch(`/api/books/${bookId}/tts-text?chapter=${chapterIndex}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || resp.statusText);
    }
    const { title, text, chapter_index, total_chapters } = await resp.json();

    this._currentChapterIndex = chapter_index;
    this._totalChapters = total_chapters;
    this._isPlaying = true;

    if (this._onStatusChange) {
      this._onStatusChange(`Playing: ${title}`, chapter_index, total_chapters);
    }

    // Strip markdown and split into sentences
    const plain = stripMarkdown(text);
    const sentences = splitSentences(plain);

    // Cap total buffer size to prevent memory issues
    const maxChars = 5000;
    const limited = [];
    let accumulated = 0;
    for (const s of sentences) {
      if (accumulated + s.length > maxChars) break;
      accumulated += s.length;
      limited.push(s);
    }

    this.sentenceQueue = limited;

    // Save progress
    this.saveProgress(bookId, chapter_index, 0, voice);

    // Start audio pipeline
    this._synthesizeNext();

    return true;
  }

  _synthesizeNext() {
    if (this._workerBusy || this.sentenceQueue.length === 0) return;

    const sentence = this.sentenceQueue.shift();
    this._workerBusy = true;
    this._activeId = ++this._activeId;

    this.worker.postMessage({
      type: 'generate',
      id: this._activeId,
      text: sentence,
      voice: this.voice,
    });

    // Update progress display
    const sentencesDone = this._totalChapters > 0
      ? this._totalChapters - this.sentenceQueue.length
      : 0;
    if (this._onStatusChange) {
      this._onStatusChange(
        `Synthesizing... (${this.sentenceQueue.length} remaining)`,
        this._currentChapterIndex,
        this._totalChapters
      );
    }
  }

  _playNextInQueue() {
    if (this.audioQueue.length === 0) {
      // Queue empty — check if we still have sentences to synthesize
      if (this.sentenceQueue.length > 0 && !this._workerBusy) {
        this._synthesizeNext();
      } else if (this.sentenceQueue.length === 0) {
        // All done for this chapter
        this._isPlaying = false;
        this._onChapterComplete();
      }
      return;
    }

    const buffer = this.audioQueue.shift();
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);

    source.onended = () => {
      // Save progress after each sentence
      const sentencesDone = this._totalChapters > 0
        ? this._totalChapters - this.sentenceQueue.length - this.audioQueue.length
        : 0;
      if (this.bookId) {
        this.saveProgress(this.bookId, this._currentChapterIndex, sentencesDone, this.voice);
      }
      this._playNextInQueue();
    };

    source.start();
  }

  _onChapterComplete() {
    if (this._onStatusChange) {
      this._onStatusChange(`Chapter ${this._currentChapterIndex + 1} complete`, this._currentChapterIndex, this._totalChapters);
    }

    // Auto-advance to next chapter if available
    if (this._currentChapterIndex + 1 < this._totalChapters) {
      this._currentChapterIndex++;
      this._playNextInQueue();
    }
  }

  _stopPlayback() {
    this._isPlaying = false;
    this.audioQueue = [];
    this.sentenceQueue = [];
    this._workerBusy = false;
    this._activeId = 0;

    if (this.worker) {
      this.worker.postMessage({ type: 'stop' });
    }

    if (this._onStatusChange) {
      this._onStatusChange('Stopped', this._currentChapterIndex, this._totalChapters);
    }
  }

  stop() {
    this._stopPlayback();
  }

  destroy() {
    this.stop();
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    this.isInitialized = false;
    this._initFailed = false;
  }

  saveProgress(bookId, chapterIndex, sentenceIndex, voice) {
    const key = `hullucinator_tts_${bookId}`;
    try {
      localStorage.setItem(key, JSON.stringify({
        lastChapterIndex: chapterIndex,
        lastSentenceIndex: sentenceIndex,
        voice,
      }));
    } catch (e) {
      console.warn('[TTS] Could not save progress:', e);
    }
  }

  loadProgress(bookId) {
    const key = `hullucinator_tts_${bookId}`;
    try {
      const data = localStorage.getItem(key);
      return data ? JSON.parse(data) : null;
    } catch (e) {
      console.warn('[TTS] Could not load progress:', e);
      return null;
    }
  }

  get isPlaying() {
    return this._isPlaying;
  }

  get isIdle() {
    return !this._isPlaying && !this._workerBusy && this.sentenceQueue.length === 0;
  }
}

const bookTTS = new BookTTSManager();
window.bookTTS = bookTTS;
