/** Sending a recording for analysis, shared by Rehearse and Improvise.
 *  The server analyzes in the background and the page polls it, so each stage is shown as it happens
 *  (decoding → transcribing → aligning → definition check). A failure never loses the audio: the
 *  server keeps the take folder (Retry re-runs it there), and the page keeps the blob (Download recording). */

import { ApiError, api } from "./api";
import { h } from "./dom";
import type { JobStatus } from "./types";

export interface RunOptions<T> {
  /** Where progress and the failure actions are shown; its content is replaced. */
  host: HTMLElement;
  blob: Blob;
  filename: string;
  /** What to say while transcribing (it names the local model or the cloud service). */
  message: string;
  /** First attempt: upload the blob and start the analysis. */
  start: () => Promise<JobStatus>;
  /** Re-run a take the server already saved, without uploading again. */
  retry: (takeId: string) => Promise<JobStatus>;
  open: (result: T) => void;
  goToReport: () => void;
  onAbandon?: () => void;
  /** Called each time an attempt fails (the failure actions are on screen). */
  onFail?: () => void;
}

const POLL_MS = 500;
const STAGE_TEXT: Record<string, string> = {
  queued: "Waiting for the speech model to finish another take…",
  starting: "Starting…",
  decoding: "Decoding the recording…",
  aligning: "Aligning the transcript with your script and measuring pauses…",
  "definition check": "Checking your [DEFINE] terms…",
  measuring: "Measuring pace, fillers, pitch and pauses…",
};

/** The last recording whose analysis failed, kept while the page is open. */
export let lastFailed: { blob: Blob; filename: string; takeId: string | null; error: string } | null = null;

function downloadName(filename: string): string {
  const ext = filename.includes(".") ? filename.slice(filename.lastIndexOf(".")) : ".webm";
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `take-two-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}${ext}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Resolves true when the analysis succeeded, false when it failed (the failure actions stay on screen). */
export async function runAnalysis<T>(o: RunOptions<T>): Promise<boolean> {
  const line = h("p", { class: "status muted", role: "status" }, o.message);
  const stepper = h("ol", { class: "stepper", "aria-label": "Analysis progress" });
  const actions = h("div", { class: "run-actions" });
  o.host.replaceChildren(stepper, line, actions);
  let takeId: string | null = null;
  let url: string | null = null;

  const say = (text: string) => { if (line.textContent !== text) line.textContent = text; };
  let stageSince = performance.now();
  let lastStage = "";
  const show = (job: JobStatus) => {
    const stage = job.stage ?? (job.status === "queued" ? "queued" : "");
    if (stage !== lastStage) {
      lastStage = stage;
      stageSince = performance.now();
      say(stage === "transcribing" ? o.message : STAGE_TEXT[stage] ?? o.message);
    }
    const at = job.stages.indexOf(stage);
    const secs = Math.floor((performance.now() - stageSince) / 1000);
    stepper.replaceChildren(...job.stages.map((s, i) => {
      const state = job.status === "done" || (at >= 0 && i < at) ? "done" : i === at ? "current" : "pending";
      return h("li", { class: state, "aria-current": state === "current" ? "step" : undefined },
        s, state === "current" && secs >= 2 ? h("span", { class: "muted" }, ` ${secs} s`) : null);
    }));
  };

  const fail = (reason: string): false => {
    lastFailed = { blob: o.blob, filename: o.filename, takeId, error: reason };
    say(`Analysis failed: ${reason}. ` + (takeId
      ? "Your recording is saved on this computer and listed under Takes."
      : "Your recording is still in this page; download it or try again."));
    line.classList.add("warn");
    url = url ?? URL.createObjectURL(o.blob);
    actions.replaceChildren(
      h("button", { class: "primary", type: "button", onClick: () => void attempt(() => (takeId ? o.retry(takeId) : o.start())) }, "Retry"),
      h("a", { class: "ghost-btn", href: url, download: downloadName(o.filename) }, "Download recording"),
    );
    if (o.onAbandon) actions.append(h("button", { class: "ghost-btn", type: "button", onClick: () => o.onAbandon?.() }, "Start over"));
    o.onFail?.();
    return false;
  };

  const attempt = async (begin: () => Promise<JobStatus>): Promise<boolean> => {
    actions.replaceChildren();
    line.classList.remove("warn");
    lastStage = "";
    say(o.message);
    let job: JobStatus;
    try {
      job = await begin();
    } catch (err) {
      takeId = (err instanceof ApiError ? err.takeId : null) ?? takeId;
      return fail(err instanceof ApiError ? err.detail : (err as Error).message);
    }
    takeId = job.take_id;
    let misses = 0;
    while (job.status === "queued" || job.status === "running") {
      show(job);
      await sleep(POLL_MS);
      try {
        job = await api.job(job.take_id);
        misses = 0;
      } catch (err) {
        // A restarted server forgets running jobs but still has the folder; a stopped one answers nothing.
        if (++misses >= 10) return fail(`lost contact with the server (${(err as Error).message})`);
      }
    }
    show(job);
    if (job.status === "failed" || !job.result) return fail(job.error ?? "the analysis did not finish");
    lastFailed = null;
    if (url) URL.revokeObjectURL(url);
    o.open(job.result as T);
    if (o.host.isConnected) o.goToReport();
    return true;
  };
  return attempt(o.start);
}

/** Shown when a recording failed earlier in this page session and the server never saved it. */
export function unsavedRecordingNote(): HTMLElement | null {
  const f = lastFailed;
  if (!f || f.takeId) return null;
  const url = URL.createObjectURL(f.blob);
  return h("p", { class: "small warn" }, `An earlier recording could not be analyzed (${f.error}). `,
    h("a", { href: url, download: downloadName(f.filename) }, "Download it"), " before closing this page.");
}
