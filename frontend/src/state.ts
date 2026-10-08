import type { Analysis, Health, Settings } from "./types";

const KEYS = { script: "marked.script", settings: "marked.settings", calib: "marked.calibration", take: "marked.lastTake" };

function read<T>(key: string): T | null {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : null;
  } catch {
    return null;
  }
}
function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage may be unavailable */
  }
}

export interface Calibration { baseline_db: number; measured_at: string }

type Listener = () => void;

class State {
  health: Health | null = null;
  settings: Settings | null = null;
  scriptText = "";
  analysis: Analysis | null = null;
  calibration: Calibration | null = read<Calibration>(KEYS.calib);
  private listeners = new Set<Listener>();

  constructor() {
    this.scriptText = read<string>(KEYS.script) ?? "";
    this.settings = read<Settings>(KEYS.settings);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private emit(): void {
    this.listeners.forEach((fn) => fn());
  }

  setScript(text: string): void {
    this.scriptText = text;
    write(KEYS.script, text);
    this.emit();
  }
  setSettings(s: Settings): void {
    this.settings = s;
    write(KEYS.settings, s);
    this.emit();
  }
  setAnalysis(a: Analysis | null): void {
    this.analysis = a;
    if (a) write(KEYS.take, a.take_id);
    this.emit();
  }
  setCalibration(c: Calibration | null): void {
    this.calibration = c;
    if (c) write(KEYS.calib, c);
    else localStorage.removeItem(KEYS.calib);
    this.emit();
  }
  lastTakeId(): string | null {
    return read<string>(KEYS.take);
  }
  effectiveSettings(): Settings {
    return { ...(this.health?.defaults ?? ({} as Settings)), ...(this.settings ?? {}) } as Settings;
  }
}

export const state = new State();
