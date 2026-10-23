// Captures mic audio, downsamples to 16 kHz mono int16 (what openWakeWord
// and Whisper expect) with a box filter, and posts 80 ms (1280-sample)
// frames to the main thread, which streams them to the Jarvis server.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / 16000; // input samples per output sample
    this.acc = 0;
    this.sum = 0;
    this.count = 0;
    this.out = new Int16Array(1280);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i];
      this.count++;
      this.acc += 1;
      if (this.acc >= this.step) {
        this.acc -= this.step;
        const s = Math.max(-1, Math.min(1, this.sum / this.count));
        this.sum = 0;
        this.count = 0;
        this.out[this.n++] = s * 32767;
        if (this.n === this.out.length) {
          this.port.postMessage(this.out.buffer, [this.out.buffer]);
          this.out = new Int16Array(1280);
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
