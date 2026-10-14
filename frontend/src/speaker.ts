/** Voices that speak a cue plan. The default is the server's local natural voice (Kokoro, on this computer:
 *  nothing is sent); without it, the browser's own speechSynthesis. A cloud voice (Gemini, Azure) is chosen by
 *  the speaker and asks for consent first, naming exactly what it sends. Synthetic audio never goes near a take
 *  or its analysis. */

import { h } from "./dom";
import { type PlanLike, toUtterances } from "./schedule";
import { state } from "./state";
import type { ServerVoice } from "./types";

export interface Speaker {
  readonly label: string;
  speak(plan: PlanLike): Promise<void>;
  stop(): void;
  available(): { ok: boolean; reason: string | null };
  /** Render ahead of time so pressing play is instant (local voices only: nothing is sent). */
  prefetch(plan: PlanLike): void;
}

export type Role = "coach" | "examiner";
export type VoiceKind = "natural" | "cloud" | "fake" | "browser";
const VOICE_KEY = (role: Role) => `taketwo.voice.${role}`;
const CONSENT_KEY = (provider: string) => `taketwo.tts.consent.${provider}`;
const LEGACY_CONSENT = "taketwo.tts.consent";  // the Azure consent from before there was more than one cloud voice
const SERVER = "server:";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, v: string): void {
  try { localStorage.setItem(key, v); } catch { /* storage may be unavailable */ }
}

const serverVoices = (): ServerVoice[] => state.health?.tts?.voices ?? [];
const consented = (v: ServerVoice) => !v.sends || read(CONSENT_KEY(v.provider)) === "yes"
  || (v.provider === "azure" && read(LEGACY_CONSENT) === "yes");

export const synth = (): SpeechSynthesis | null => ("speechSynthesis" in window ? window.speechSynthesis : null);

/** The browser's voices, English first. Empty until the browser has loaded them (see onVoicesChanged). */
export function browserVoices(): SpeechSynthesisVoice[] {
  const v = synth()?.getVoices() ?? [];
  return [...v].sort((a, b) => Number(b.lang.startsWith("en")) - Number(a.lang.startsWith("en")) || a.name.localeCompare(b.name));
}

/** Resolves when the browser has its voices, or after `ms` (some browsers load them a moment after the page).
 *  With a server voice in use there is nothing to wait for. */
export function voicesReady(ms = 1500): Promise<void> {
  const s = synth();
  const allServer = (["coach", "examiner"] as const).every((r) => resolve(r).server);
  if (!s || s.getVoices().length || allServer) return Promise.resolve();
  return new Promise((resolve) => {
    const t = window.setTimeout(resolve, ms);
    s.addEventListener("voiceschanged", () => { window.clearTimeout(t); resolve(); }, { once: true });
  });
}

export function onVoicesChanged(fn: () => void): () => void {
  synth()?.addEventListener("voiceschanged", fn);
  return () => synth()?.removeEventListener("voiceschanged", fn);
}

/** The browser voice a role speaks with: the speaker's pick if loaded, else the default English one. */
function browserVoice(role: Role): SpeechSynthesisVoice | null {
  const want = read(VOICE_KEY(role));
  const vs = browserVoices();
  return vs.find((v) => v.voiceURI === want) ?? vs.find((v) => v.default && v.lang.startsWith("en")) ?? vs[0] ?? null;
}

/** Which voice a role uses: the speaker's pick if it still exists, else the server's default for the role
 *  (a local voice, never a cloud one), else the browser's voice. A browser pick that is gone from the browser
 *  (once its voices have loaded) is not a choice any more. */
function resolve(role: Role): { server: ServerVoice | null; explicit: boolean } {
  const pick = read(VOICE_KEY(role));
  const vs = serverVoices();
  if (pick?.startsWith(SERVER)) {
    const v = vs.find((x) => x.id === pick.slice(SERVER.length));
    if (v) return { server: v, explicit: true };
  } else if (pick === "server") {  // the choice from before there was more than one server voice
    const v = vs.find((x) => x.local) ?? vs[0];
    if (v) return { server: v, explicit: true };
  } else if (pick) {  // a browser voice; it may not be loaded yet
    const bv = browserVoices();
    if (!bv.length || bv.some((v) => v.voiceURI === pick)) return { server: null, explicit: true };
  }
  const def = state.health?.tts?.default?.[role];
  return { server: vs.find((x) => x.id === def) ?? null, explicit: false };
}

/** What kind of voice a role is using now, for the notes beside it. */
export function voiceKind(role: Role): VoiceKind {
  const v = resolve(role).server;
  if (!v) return "browser";
  return v.provider === "fake" ? "fake" : v.local ? "natural" : "cloud";
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
  private voice(): SpeechSynthesisVoice | null { return browserVoice(this.role); }
  available() {
    const s = synth();
    if (!s) return { ok: false, reason: "This browser has no speech synthesis, so the plan is shown as text only." };
    if (!s.getVoices().length) return { ok: false, reason: "No speech voices are loaded in this browser (some load a moment after the page; others have none installed), so the plan is shown as text only." };
    return { ok: true, reason: null };
  }
  prefetch(): void { /* nothing to render ahead */ }
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

interface Rendered { url: string; starts: (number | null)[] }

/** Rendered audio by voice and plan, so a line heard twice, or prefetched, plays at once. */
const rendered = new Map<string, Promise<Rendered>>();
const RENDERED_MAX = 12;

async function render(voice: ServerVoice, plan: PlanLike): Promise<Rendered> {
  const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan, voice: voice.id, consent: consented(voice) }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail);
  let starts: (number | null)[] = [];
  try { starts = JSON.parse(r.headers.get("X-Segment-Starts") ?? "[]"); } catch { /* highlight the first segment only */ }
  return { url: URL.createObjectURL(await r.blob()), starts };
}

function cached(voice: ServerVoice, plan: PlanLike): Promise<Rendered> {
  const key = `${voice.id}|${JSON.stringify(plan)}`;
  let p = rendered.get(key);
  if (p) {
    rendered.delete(key);  // most recent last
  } else {
    p = render(voice, plan);
    p.catch(() => rendered.delete(key));
  }
  rendered.set(key, p);
  while (rendered.size > RENDERED_MAX) {
    const [old, op] = rendered.entries().next().value as [string, Promise<Rendered>];
    rendered.delete(old);
    op.then((x) => URL.revokeObjectURL(x.url), () => undefined);
  }
  return p;
}

class ServerSpeaker implements Speaker {
  private audio: HTMLAudioElement | null = null;
  private done: (() => void) | null = null;
  private run = 0;  // each speak() and stop() starts a new run; a render that finishes for an old run is not played
  constructor(private role: Role, private fallback: BrowserSpeaker) {}
  private voice(): ServerVoice | null { return resolve(this.role).server; }
  get label(): string {
    const v = this.voice();
    return v ? `${v.label}${v.local && v.provider !== "fake" ? " (on this computer)" : ""}` : "server voice";
  }
  available() {
    const v = this.voice();
    if (!v) return { ok: false, reason: state.health?.tts?.reason ?? "No server voice is available." };
    if (!consented(v)) return { ok: false, reason: `This voice sends ${v.sends}; choose it again to give consent.` };
    return { ok: true, reason: null };
  }
  prefetch(plan: PlanLike): void {
    const v = this.voice();
    if (v?.local && plan.segments.length) cached(v, plan).catch(() => undefined);
  }
  async speak(plan: PlanLike): Promise<void> {
    this.stop();
    const run = this.run;
    const v = this.voice();
    if (!v) throw new Error("No server voice is available.");
    let got: Rendered;
    try {
      got = await cached(v, plan);
    } catch (err) {
      // A local voice that is not ready (still downloading, or failed) hands over to the browser's voice and
      // says so; a cloud voice the speaker chose never falls back silently.
      if (!v.local || !this.fallback.available().ok) throw err;
      emitNote(`${v.label} is not available right now (${(err as Error).message}), so your browser's voice is speaking.`);
      if (run !== this.run) return;
      return this.fallback.speak(plan);
    }
    if (run !== this.run) return;
    // Its own element, never the shared take player: the demonstration must not be mistaken for a take.
    const a = new Audio(got.url);
    this.audio = a;
    let current = -2;
    const tick = () => {
      let i = -1;
      got.starts.forEach((s, k) => { if (s !== null && s <= a.currentTime + 0.05) i = k; });
      // No timings (a cloud voice returns none): highlight the first segment, so the line shows as playing.
      if (i === -1) i = Math.max(0, got.starts.findIndex((s) => s !== null));
      if (i !== current) { current = i; emitSegment(i); }
    };
    a.addEventListener("timeupdate", tick);
    tick();
    await new Promise<void>((resolve) => {
      this.done = resolve;
      a.onended = () => resolve();
      a.onerror = () => resolve();
      a.play().catch(() => resolve());
    });
    a.removeEventListener("timeupdate", tick);
    emitSegment(-1);
  }
  stop(): void {
    this.run++;
    this.audio?.pause();
    this.audio = null;
    this.done?.();
    this.done = null;
    this.fallback.stop();
    emitSegment(-1);
  }
}

const speakers: Partial<Record<Role, { browser: BrowserSpeaker; server: ServerSpeaker }>> = {};

function pair(role: Role) {
  if (!speakers[role]) {
    const browser = new BrowserSpeaker(role);
    speakers[role] = { browser, server: new ServerSpeaker(role, browser) };
  }
  return speakers[role]!;
}

/** The voice this role uses now (see resolve). */
export function getSpeaker(role: Role): Speaker {
  const p = pair(role);
  return resolve(role).server ? p.server : p.browser;
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

// A note about the voice itself (the natural voice handed over to the browser's), for the status line.
const noteListeners = new Set<(msg: string) => void>();
function emitNote(msg: string): void {
  noteListeners.forEach((fn) => fn(msg));
}
export function onVoiceNote(fn: (msg: string) => void): () => void {
  noteListeners.add(fn);
  return () => noteListeners.delete(fn);
}

/** A voice picker for one role: the server's voices (natural ones first), then the browser's own. */
export function voicePicker(role: Role, label: string): HTMLElement {
  const sel = h("select", { class: "label-input voice-pick", "aria-label": label }) as HTMLSelectElement;
  const note = h("small", { class: "muted" });
  const fill = () => {
    sel.replaceChildren();
    const vs = serverVoices();
    const group = (title: string, items: ServerVoice[]) => {
      if (!items.length) return;
      sel.append(h("optgroup", { label: title }, ...items.map((v) => h("option", { value: SERVER + v.id }, v.label))));
    };
    group("Natural voices (on this computer)", vs.filter((v) => v.local && v.provider !== "fake"));
    group("Cloud voices (send script text)", vs.filter((v) => !v.local));
    group("Development", vs.filter((v) => v.provider === "fake"));
    const bv = browserVoices();
    const browserOpts = bv.length
      ? bv.map((v) => h("option", { value: v.voiceURI }, `${v.name} (${v.lang}${v.localService ? "" : ", online voice"})`))
      : [h("option", { value: "" }, synth() ? "Browser voice (none loaded yet)" : "No browser voice")];
    sel.append(h("optgroup", { label: "Browser voices" }, ...browserOpts));
    // Show the voice that will actually speak: a server voice, or the browser voice BrowserSpeaker would use.
    const { server } = resolve(role);
    const want = server ? SERVER + server.id : browserVoice(role)?.voiceURI ?? "";
    sel.value = [...sel.options].some((o) => o.value === want) ? want : sel.options[0]?.value ?? "";
    const chosenServer = vs.find((v) => SERVER + v.id === sel.value);
    const chosenBrowser = bv.find((v) => v.voiceURI === sel.value);
    note.textContent = chosenServer
      ? chosenServer.provider === "fake" ? " A development stand-in: tones in place of speech."
        : chosenServer.local ? ` A neural voice running on this computer; nothing is sent.${chosenServer.note ? ` Note: ${chosenServer.note}.` : ""}`
        : ` Sends ${chosenServer.sends}. Your recordings are never sent.`
      : chosenBrowser && !chosenBrowser.localService ? " This browser voice is provided online by the browser's maker, so the text may leave this computer."
      : !vs.length && state.health?.tts?.unavailable?.length ? ` ${state.health.tts.unavailable[0]}` : "";
  };
  sel.addEventListener("change", () => {
    const v = serverVoices().find((x) => SERVER + x.id === sel.value);
    if (v && !consented(v)) {
      if (!confirm(`This voice sends ${v.sends}. Your recordings are never sent. Use it?`)) {
        fill();
        return;
      }
      write(CONSENT_KEY(v.provider), "yes");
    }
    write(VOICE_KEY(role), sel.value);
    stopAll();
    fill();
    sel.dispatchEvent(new CustomEvent("voicechange", { bubbles: true }));
  });
  fill();
  // Refill when the browser's voices arrive; once the picker has been shown and removed, stop listening.
  let shown = false;
  const off = onVoicesChanged(() => {
    if (!sel.isConnected && shown) { off(); return; }
    shown ||= sel.isConnected;
    fill();
  });
  return h("label", { class: "small voice-label" }, `${label} `, sel, note);
}
