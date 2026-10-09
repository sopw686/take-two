/** Microphone capture: MediaRecorder for the take, a Meter for live loudness. One instance per recording. */

import { Meter, extFor, pickMimeType } from "./meter";

export class Recorder {
  private stream: MediaStream | null = null;
  private rec: MediaRecorder | null = null;
  private meter: Meter | null = null;
  private chunks: Blob[] = [];
  private mime = "";

  get recording(): boolean {
    return this.rec?.state === "recording";
  }

  async start(onLevel?: (db: number) => void): Promise<void> {
    // Raw signal: the browser's processing would distort the loudness and pitch measurements.
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    if (onLevel) {
      this.meter = new Meter();
      this.meter.onLevel = onLevel;
      await this.meter.start(this.stream);
    }
    this.mime = pickMimeType();
    this.rec = new MediaRecorder(this.stream, this.mime ? { mimeType: this.mime } : undefined);
    this.chunks = [];
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start(250);
  }

  /** Stop and return the recording with a filename whose extension matches its container. */
  stop(): Promise<{ blob: Blob; filename: string }> {
    return new Promise((resolve) => {
      const rec = this.rec;
      if (!rec || rec.state !== "recording") {
        this.release();
        resolve({ blob: new Blob([]), filename: "take.webm" });
        return;
      }
      rec.onstop = () => {
        const blob = new Blob(this.chunks, { type: rec.mimeType || this.mime || "audio/webm" });
        this.release();
        resolve({ blob, filename: `take.${extFor(blob.type)}` });
      };
      rec.stop();
    });
  }

  /** Stop without keeping anything. */
  cancel(): void {
    if (this.rec && this.rec.state === "recording") {
      this.rec.onstop = null;
      this.rec.stop();
    }
    this.release();
  }

  private release(): void {
    this.meter?.stop();
    this.meter = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.rec = null;
  }
}

/** Show a dBFS level on a meter bar, relative to the user's calibrated level when there is one. */
export function showLevel(db: number, bar: HTMLElement, label: HTMLElement, baselineDb: number | null): void {
  if (baselineDb !== null) {
    const rel = db - baselineDb;
    bar.style.width = `${Math.max(0, Math.min(100, 50 + rel * 2.5))}%`;
    bar.className = "meter-fill " + (rel > 6 ? "loud" : rel < -12 ? "quiet" : "ok");
    label.textContent = db < -60 ? "silence" : `${rel >= 0 ? "+" : ""}${rel.toFixed(0)} dB relative to your calibrated level`;
  } else {
    bar.style.width = `${Math.max(0, Math.min(100, (db + 60) * (100 / 60)))}%`;
    bar.className = "meter-fill ok";
    label.textContent = db < -60 ? "silence" : `${db.toFixed(0)} dBFS (calibrate on the Rehearse tab to make this relative to you)`;
  }
}
