// AudioWorklet that turns the microphone into 16 kHz mono 16-bit PCM and posts
// it to the main thread in 100 ms chunks (1600 samples), ready for Whisper.
// Downsampling is a running box-filter average, which also acts as a crude
// anti-aliasing low-pass: good enough for speech recognition.
const TARGET_RATE = 16000;
const CHUNK = 1600;

class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;   // e.g. 48000 / 16000 = 3
    this.pos = 0;
    this.sum = 0;
    this.cnt = 0;
    this.buf = new Int16Array(CHUNK);
    this.n = 0;
  }

  emit(v) {
    v = Math.max(-1, Math.min(1, v));
    this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
    if (this.n === CHUNK) {
      this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
      this.buf = new Int16Array(CHUNK);
      this.n = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    const ch = input[0];
    for (let k = 0; k < ch.length; k++) {
      this.sum += ch[k];
      this.cnt++;
      if (++this.pos >= this.ratio) {
        this.pos -= this.ratio;
        this.emit(this.sum / this.cnt);
        this.sum = 0;
        this.cnt = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
