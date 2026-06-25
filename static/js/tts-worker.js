/**
 * TTS Web Worker — Kokoro text-to-speech inference.
 *
 * Runs Kokoro model loading and sentence synthesis off the main thread.
 * Uses ONNX Runtime WASM (multi-threaded when SharedArrayBuffer is available).
 *
 * Messages received:
 *   { type: 'init', modelId?, dtype?, device? }  — load model
 *   { type: 'generate', id, text, voice }          — synthesize sentence
 *   { type: 'stop' }                                — unload model
 *
 * Messages sent:
 *   { type: 'ready', device, dtype }               — model loaded
 *   { type: 'initError', message }                 — model load failed
 *   { type: 'audio', id, wav: ArrayBuffer, sampleRate } — synthesis result
 *   { type: 'error', id, message }                 — synthesis failed
 */
import { KokoroTTS, env } from './vendor/kokoro.web.js';

// Configure ONNX Runtime WASM multi-threading for faster inference
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
