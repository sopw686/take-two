/** Microphone loudness via the Web Audio API. Reports dBFS; the UI shows it relative to the user's calibration. */

export class Meter {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private buf: Float32Array | null = null;
  private raf = 0;
  onLevel: ((db: number) => void) | null = null;

  async start(stream: MediaStream): Promise<void> {
    this.ctx = new AudioContext();
    const src = this.ctx.createMediaStreamSource(stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.6;
    src.connect(this.analyser);
    this.buf = new Float32Array(this.analyser.fftSize);
    const tick = () => {
      if (!this.analyser || !this.buf) return;
      this.analyser.getFloatTimeDomainData(this.buf);
      let sum = 0;
      for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
      const rms = Math.sqrt(sum / this.buf.length);
      const db = 20 * Math.log10(rms + 1e-7);
      this.onLevel?.(db);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop(): void {
    cancelAnimationFrame(this.raf);
    this.analyser?.disconnect();
    this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.analyser = null;
  }
}

export function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4", ""];
  for (const c of candidates) if (!c || MediaRecorder.isTypeSupported(c)) return c;
  return "";
}

export function extFor(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  return "webm";
}
