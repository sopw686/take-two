/** Voices that speak a cue plan. The default is the browser's own speechSynthesis: local, no key, no network.
 *  The server voice (Azure Speech, or the labelled fake) is optional, chosen by the speaker, and a cloud one asks
 *  for consent first, naming exactly what it sends. Synthetic audio never goes near a take or its analysis. */

import { h } from "./dom";
import { type PlanLike, toUtterances } from "./schedule";
import { state } from "./state";

export interface Speaker {
  readonly label: string;
  speak(plan: PlanLike): Promise<void>;
  stop(): void;
  available(): { ok: boolean; reason: string | null };
}

export type Role = "coach" | "examiner";
const VOICE_KEY = (role: Role) => `taketwo.voice.${role}`;
const CONSENT_KEY = "taketwo.tts.consent";
const SERVER = "server";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, v: string): void {
  try { localStorage.setItem(key, v); } catch { /* storage may be unavailable */ }
}

export const synth = (): SpeechSynthesis | null => ("speechSynthesis" in window ? window.speechSynthesis : null);

/** The browser's voices, English first. Empty until the browser has loaded them (see onVoicesChanged). */
export function browserVoices(): SpeechSynthesisVoice[] {
  const v = synth()?.getVoices() ?? [];
  return [...v].sort((a, b) => Number(b.lang.startsWith("en")) - Number(a.lang.startsWith("en")) || a.name.localeCompare(b.name));
}

/** Resolves when the browser has its voices, or after `ms` (some browsers load them a moment after the page). */
export function voicesReady(ms = 1500): Promise<void> {
  const s = synth();
  if (!s || s.getVoices().length) return Promise.resolve();
  return new Promise((resolve) => {
    const t = window.setTimeout(resolve, ms);
    s.addEventListener("voiceschanged", () => { window.clearTimeout(t); resolve(); }, { once: true });
  });
}

export function onVoicesChanged(fn: () => void): void {
  synth()?.addEventListener("voiceschanged", fn);
}

type Token = { stopped: boolean; cancel?: () => void };

const wait = (ms: number, token: Token) => new Promise<void>((resolve) => {
  if (ms <= 0 || token.stopped) return resolve();
  const t = window.setTimeout(resolve, ms);
  token.cancel = () => { window.clearTimeout(t); resolve(); };
});

class BrowserSpeaker implements Speaker {
  private token: Token = { stopped: true };
  constructor(private role: Role) {}
  get label(): string {
    const v = this.voice();
    return `browser voice${v ? `: ${v.name}` : ""} (on this computer)`;
  }
  private voice(): SpeechSynthesisVoice | null {
    const want = read(VOICE_KEY(this.role));
    const vs = browserVoices();
    return vs.find((v) => v.voiceURI === want) ?? vs.find((v) => v.default && v.lang.startsWith("en")) ?? vs[0] ?? null;
  }
  available() {
    const s = synth();
    if (!s) return { ok: false, reason: "This browser has no speech synthesis, so the plan is shown as text only." };
    if (!s.getVoices().length) return { ok: false, reason: "No speech voices are loaded in this browser (some load a moment after the page; others have none installed), so the plan is shown as text only." };
    return { ok: true, reason: null };
  }
  async speak(plan: PlanLike): Promise<void> {
    this.stop();
    const s = synth();
    if (!s || !this.available().ok) throw new Error(this.available().reason ?? "No voice");
    const token: Token = { stopped: false };
    this.token = token;
    const { leadMs, utterances } = toUtterances(plan);
    const voice = this.voice();
    await wait(leadMs, token);
    for (const u of utterances) {
      if (token.stopped) return;
      emitSegment(u.segment);
      await new Promise<void>((resolve) => {
        const ut = new SpeechSynthesisUtterance(u.text);
        if (voice) ut.voice = voice;
        ut.lang = voice?.lang ?? "en-US";
        ut.rate = u.rate;
        ut.pitch = u.pitch;
        ut.volume = u.volume;
        ut.onend = () => resolve();
        ut.onerror = () => resolve();
        token.cancel = () => resolve();
        s.speak(ut);
      });
      await wait(u.gapAfterMs, token);
    }
    emitSegment(-1);
  }
  stop(): void {
    this.token.stopped = true;
    this.token.cancel?.();
    synth()?.cancel();
    emitSegment(-1);
  }
}

class ServerSpeaker implements Speaker {
  private audio: HTMLAudioElement | null = null;
  private done: (() => void) | null = null;
  get label(): string {
    const t = state.health?.tts;
    return t?.label ?? "server voice";
  }
  available() {
    const t = state.health?.tts;
    if (!t?.available) return { ok: false, reason: t?.reason ?? "No server voice is configured." };
    if (t.sends && read(CONSENT_KEY) !== "yes") return { ok: false, reason: `This voice sends ${t.sends}; choose it again to give consent.` };
    return { ok: true, reason: null };
  }
  async speak(plan: PlanLike): Promise<void> {
    this.stop();
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, consent: read(CONSENT_KEY) === "yes" }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail);
    const url = URL.createObjectURL(await r.blob());
    // Its own element, never the shared take player: the demonstration must not be mistaken for a take.
    const a = new Audio(url);
    this.audio = a;
    emitSegment(0);
    await new Promise<void>((resolve) => {
      this.done = resolve;
      a.onended = () => resolve();
      a.onerror = () => resolve();
      a.play().catch(() => resolve());
    });
    URL.revokeObjectURL(url);
    emitSegment(-1);
  }
  stop(): void {
    this.audio?.pause();
    this.audio = null;
    this.done?.();
    this.done = null;
    emitSegment(-1);
  }
}

const speakers: Partial<Record<Role, { browser: BrowserSpeaker; server: ServerSpeaker }>> = {};

/** The voice this role uses now: the speaker's pick, else the browser voice. */
export function getSpeaker(role: Role): Speaker {
  const pair = speakers[role] ?? (speakers[role] = { browser: new BrowserSpeaker(role), server: new ServerSpeaker() });
  return read(VOICE_KEY(role)) === SERVER && state.health?.tts?.available ? pair.server : pair.browser;
}

/** Stop every voice (a tab change, a recording about to start). */
export function stopAll(): void {
  for (const p of Object.values(speakers)) {
    p?.browser.stop();
    p?.server.stop();
  }
}

// Which segment is being said, for the on-screen highlight.
const segListeners = new Set<(i: number) => void>();
function emitSegment(i: number): void {
  segListeners.forEach((fn) => fn(i));
}
export function onSegment(fn: (i: number) => void): () => void {
  segListeners.add(fn);
  return () => segListeners.delete(fn);
}

/** A voice picker for one role: the browser's voices, plus the server voice when one is configured. */
export function voicePicker(role: Role, label: string): HTMLElement {
  const sel = h("select", { class: "label-input voice-pick", "aria-label": label }) as HTMLSelectElement;
  const note = h("small", { class: "muted" });
  const fill = () => {
    const cur = read(VOICE_KEY(role));
    sel.replaceChildren();
    const vs = browserVoices();
    if (!vs.length) sel.append(h("option", { value: "" }, synth() ? "Browser voice (none loaded yet)" : "No browser voice"));
    for (const v of vs) sel.append(h("option", { value: v.voiceURI }, `${v.name} (${v.lang}${v.localService ? "" : ", online voice"})`));
    const t = state.health?.tts;
    if (t?.available) sel.append(h("option", { value: SERVER }, t.sends ? `${t.label}: cloud, sends script text` : `${t.label}`));
    sel.value = cur && [...sel.options].some((o) => o.value === cur) ? cur : sel.options[0]?.value ?? "";
    const chosen = vs.find((v) => v.voiceURI === sel.value);
    note.textContent = sel.value === SERVER
      ? (t?.sends ? ` Sends ${t.sends}. Your recordings are never sent.` : " A development stand-in: tones in place of speech.")
      : chosen && !chosen.localService ? " This browser voice is provided online by the browser's maker, so the text may leave this computer." : "";
  };
  sel.addEventListener("change", () => {
    const t = state.health?.tts;
    if (sel.value === SERVER && t?.sends && read(CONSENT_KEY) !== "yes") {
      if (!confirm(`This voice sends ${t.sends}. Your recordings are never sent. Use it?`)) {
        fill();
        return;
      }
      write(CONSENT_KEY, "yes");
    }
    write(VOICE_KEY(role), sel.value);
    stopAll();
    fill();
  });
  fill();
  onVoicesChanged(fill);
  return h("label", { class: "small voice-label" }, `${label} `, sel, note);
}
