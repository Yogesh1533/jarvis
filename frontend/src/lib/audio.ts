// Mic capture (streamed to the server), speech playback, live levels for
// the reactor, and a few synthesized interface sounds.

type Sfx = "boot" | "wake" | "alert" | "notify" | "blip";

class AudioEngine {
  ctx: AudioContext | null = null;
  private out: AnalyserNode | null = null;
  private micAnalyser: AnalyserNode | null = null;
  private micStream: MediaStream | null = null;
  private micNode: AudioWorkletNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private finish: ((interrupted: boolean) => void) | null = null;
  private buf = new Float32Array(1024);
  private browserSpeaking = false;
  sounds = true;

  async init() {
    if (this.ctx) return;
    this.ctx = new AudioContext();
    this.out = this.ctx.createAnalyser();
    this.out.fftSize = 1024;
    this.out.connect(this.ctx.destination);
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  get micActive() {
    return !!this.micStream;
  }

  async startMic(onFrame: (buf: ArrayBuffer) => void) {
    if (!this.ctx || this.micStream) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await this.ctx.audioWorklet.addModule("/pcm-worklet.js");
    const src = this.ctx.createMediaStreamSource(stream);
    this.micAnalyser = this.ctx.createAnalyser();
    this.micAnalyser.fftSize = 1024;
    src.connect(this.micAnalyser);
    const node = new AudioWorkletNode(this.ctx, "pcm-capture");
    node.port.onmessage = (e) => onFrame(e.data as ArrayBuffer);
    // A silent sink keeps the worklet pulled by the audio graph.
    const sink = this.ctx.createGain();
    sink.gain.value = 0;
    src.connect(node).connect(sink).connect(this.ctx.destination);
    this.micStream = stream;
    this.micNode = node;
  }

  stopMic() {
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micNode?.disconnect();
    this.micStream = null;
    this.micNode = null;
    this.micAnalyser = null;
  }

  /** 0..1 loudness of the mic or of Jarvis's voice. */
  level(which: "mic" | "out"): number {
    if (which === "out" && this.browserSpeaking) {
      const t = performance.now() / 1000;
      return 0.35 + 0.25 * Math.abs(Math.sin(t * 9.1) * Math.sin(t * 3.7));
    }
    const a = which === "mic" ? this.micAnalyser : this.out;
    if (!a) return 0;
    a.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.min(1, Math.sqrt(sum / this.buf.length) * 4.5);
  }

  // ── Spoken replies arrive sentence by sentence ────────────────────
  private utterance: number | null = null;
  private segments = new Map<number, { audio: string | null; text: string; last: boolean }>();
  private nextSeq = 0;
  private pumpingFor: number | null = null;
  private fillerPlaying: Promise<boolean> | null = null;
  private onUtteranceDone: ((id: number) => void) | null = null;

  /** Called once per utterance when its last sentence has played. */
  onDone(fn: (id: number) => void) {
    this.onUtteranceDone = fn;
  }

  /** Queue one sentence of utterance `id`; a new id replaces the old one. */
  push(id: number, seq: number, b64: string | null, text: string, last: boolean) {
    if (id !== this.utterance) {
      if (this.fillerPlaying) this.utterance = null; // let "one moment" finish
      else this.stop();
      this.utterance = id;
      this.segments.clear();
      this.nextSeq = 0;
    }
    this.segments.set(seq, { audio: b64, text, last });
    this.pump();
  }

  private async pump() {
    const id = this.utterance;
    if (id === null || this.pumpingFor === id) return;
    this.pumpingFor = id;
    try {
      while (this.utterance === id && this.segments.has(this.nextSeq)) {
        const seg = this.segments.get(this.nextSeq)!;
        this.segments.delete(this.nextSeq);
        this.nextSeq += 1;
        if (this.fillerPlaying) await this.fillerPlaying;
        if (id !== this.utterance) return;
        let interrupted: boolean;
        try {
          interrupted = seg.audio ? await this.play(seg.audio) : await this.speakBrowser(seg.text);
        } catch {
          interrupted = await this.speakBrowser(seg.text);
        }
        if (interrupted || id !== this.utterance) return;
        if (seg.last) {
          this.utterance = null;
          this.onUtteranceDone?.(id);
          return;
        }
      }
    } finally {
      if (this.pumpingFor === id) this.pumpingFor = null;
    }
  }

  /** A short "one moment" while Jarvis works; skipped if already talking. */
  async filler(b64: string) {
    if (this.speaking || !this.ctx) return;
    const playing = this.play(b64).catch(() => false);
    this.fillerPlaying = playing;
    await playing;
    if (this.fillerPlaying === playing) this.fillerPlaying = null;
  }

  /** Play base64 audio. Resolves false when it finished, true when interrupted. */
  private async play(b64: string): Promise<boolean> {
    if (!this.ctx || !this.out) return false;
    this.stopSound();
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buffer = await this.ctx.decodeAudioData(bytes.buffer);
    return new Promise((resolve) => {
      const src = this.ctx!.createBufferSource();
      src.buffer = buffer;
      src.connect(this.out!);
      this.source = src;
      this.finish = resolve;
      src.onended = () => {
        if (this.source === src) {
          this.source = null;
          this.finish = null;
          resolve(false);
        }
      };
      src.start();
    });
  }

  /** Fallback when the server has no voice configured. */
  private speakBrowser(text: string): Promise<boolean> {
    this.stopSound();
    if (!("speechSynthesis" in window)) return Promise.resolve(false);
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      const voices = speechSynthesis.getVoices();
      u.voice =
        voices.find((v) => /Daniel|Arthur|Google UK English Male/.test(v.name)) ||
        voices.find((v) => v.lang === "en-GB") ||
        null;
      u.rate = 1.03;
      this.browserSpeaking = true;
      this.finish = resolve;
      const done = () => {
        if (!this.browserSpeaking) return;
        this.browserSpeaking = false;
        this.finish = null;
        resolve(false);
      };
      u.onend = done;
      u.onerror = done;
      speechSynthesis.speak(u);
    });
  }

  /** Stop speaking now and drop the rest of the utterance. */
  stop() {
    this.utterance = null;
    this.segments.clear();
    this.stopSound();
  }

  private stopSound() {
    const finish = this.finish;
    this.finish = null;
    if (this.source) {
      const s = this.source;
      this.source = null;
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    if (this.browserSpeaking) {
      this.browserSpeaking = false;
      speechSynthesis.cancel();
    }
    finish?.(true);
  }

  get speaking() {
    return !!this.source || this.browserSpeaking || this.utterance !== null;
  }

  sfx(kind: Sfx) {
    const ctx = this.ctx;
    if (!ctx || !this.sounds) return;
    const now = ctx.currentTime;
    const tone = (freq: number, start: number, dur: number, type: OscillatorType, vol: number, to?: number) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, now + start);
      if (to) o.frequency.exponentialRampToValueAtTime(to, now + start + dur);
      g.gain.setValueAtTime(0, now + start);
      g.gain.linearRampToValueAtTime(vol, now + start + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
      o.connect(g).connect(ctx.destination);
      o.start(now + start);
      o.stop(now + start + dur + 0.05);
    };
    switch (kind) {
      case "boot":
        tone(120, 0, 1.3, "sine", 0.12, 900);
        tone(240, 0.15, 1.2, "triangle", 0.04, 1800);
        tone(1760, 1.05, 0.5, "sine", 0.05);
        break;
      case "wake":
        tone(880, 0, 0.12, "triangle", 0.09);
        tone(1320, 0.08, 0.18, "triangle", 0.08);
        break;
      case "alert":
        tone(520, 0, 0.18, "square", 0.035);
        tone(390, 0.2, 0.26, "square", 0.035);
        break;
      case "notify":
        tone(660, 0, 0.14, "sine", 0.08);
        tone(880, 0.12, 0.14, "sine", 0.08);
        tone(1175, 0.24, 0.3, "sine", 0.08);
        break;
      case "blip":
        tone(1400, 0, 0.06, "sine", 0.04);
        break;
    }
  }
}

export const audio = new AudioEngine();
