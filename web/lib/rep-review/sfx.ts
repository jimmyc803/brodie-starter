// Synthesized UI sounds for the rep review player (Web Audio, no files): a mechanical counter click, a slam for the
// title, a stamp for a flagged rep and a chime for the set score. Everything also feeds `stream` so Export records it.
export class Sfx {
  private ctx: AudioContext | null = null;
  private out: GainNode | null = null;
  private dest: MediaStreamAudioDestinationNode | null = null;
  private noiseBuf: AudioBuffer | null = null;
  muted = false;

  // Must first run inside a user gesture (the tap that opened the player) so the context may start.
  ensure(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.ctx) {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      this.ctx = new Ctor();
      this.out = this.ctx.createGain();
      this.out.gain.value = this.muted ? 0 : 0.9;
      this.out.connect(this.ctx.destination);
      this.dest = this.ctx.createMediaStreamDestination();
      this.out.connect(this.dest);
      const len = Math.floor(this.ctx.sampleRate * 0.5);
      this.noiseBuf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const data = this.noiseBuf.getChannelData(0);
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    }
    if (this.ctx.state === "suspended") void this.ctx.resume().catch(() => {});
    return this.ctx;
  }

  get stream(): MediaStream | null {
    this.ensure();
    return this.dest?.stream ?? null;
  }

  setMuted(m: boolean) {
    this.muted = m;
    if (this.ctx && this.out) this.out.gain.setTargetAtTime(m ? 0 : 0.9, this.ctx.currentTime, 0.01);
  }

  private tone(type: OscillatorType, f0: number, f1: number, dur: number, gain: number, at = 0) {
    const ctx = this.ensure();
    if (!ctx || !this.out) return;
    const t = ctx.currentTime + at;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.003);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.out);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  private noise(filter: BiquadFilterType, freq: number, dur: number, gain: number, at = 0, q = 0.8, freqTo?: number) {
    const ctx = this.ensure();
    if (!ctx || !this.out || !this.noiseBuf) return;
    const t = ctx.currentTime + at;
    const src = ctx.createBufferSource();
    src.buffer = this.noiseBuf;
    const f = ctx.createBiquadFilter();
    f.type = filter;
    f.Q.value = q;
    f.frequency.setValueAtTime(freq, t);
    if (freqTo) f.frequency.exponentialRampToValueAtTime(freqTo, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.002);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(this.out);
    src.start(t);
    src.stop(t + dur + 0.02);
  }

  // Tally counter: a bright tick, a hollow body knock and a tiny release click.
  click() {
    this.noise("highpass", 3800, 0.022, 0.55);
    this.tone("square", 2300, 1500, 0.018, 0.08);
    this.tone("sine", 320, 140, 0.05, 0.35);
    this.noise("bandpass", 1800, 0.012, 0.25, 0.045, 3);
  }

  whoosh() {
    this.noise("bandpass", 300, 0.32, 0.22, 0, 1.2, 2600);
  }

  slam() {
    this.tone("sine", 140, 38, 0.32, 0.9);
    this.noise("lowpass", 900, 0.14, 0.5);
  }

  stamp() {
    this.tone("sine", 110, 32, 0.4, 1);
    this.tone("square", 92, 60, 0.09, 0.12);
    this.noise("lowpass", 1400, 0.18, 0.6);
    this.noise("highpass", 5000, 0.03, 0.3);
  }

  chime() {
    this.tone("triangle", 880, 870, 0.7, 0.18);
    this.tone("triangle", 1320, 1310, 0.55, 0.1, 0.05);
    this.tone("sine", 220, 110, 0.25, 0.3);
  }

  close() {
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
