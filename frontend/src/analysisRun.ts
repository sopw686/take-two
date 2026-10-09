/** Sending a recording for analysis, shared by Rehearse and Improvise.
 *  A failure never loses the audio: the server keeps the take folder (Retry re-runs it there),
 *  and the page keeps the blob (Download recording saves it). */

import { ApiError } from "./api";
import { h } from "./dom";

export interface RunOptions<T> {
  /** Where progress and the failure actions are shown; its content is replaced. */
  host: HTMLElement;
  blob: Blob;
  filename: string;
  message: string;
  /** First attempt: upload the blob. */
  start: () => Promise<T>;
  /** Re-run a take the server already saved, without uploading again. */
  retry: (takeId: string) => Promise<T>;
  open: (result: T) => void;
  goToReport: () => void;
  onAbandon?: () => void;
}

/** The last recording whose analysis failed, kept while the page is open. */
export let lastFailed: { blob: Blob; filename: string; takeId: string | null; error: string } | null = null;

function downloadName(filename: string): string {
  const ext = filename.includes(".") ? filename.slice(filename.lastIndexOf(".")) : ".webm";
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `marked-take-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}${ext}`;
}

/** Resolves true when the analysis succeeded, false when it failed (the failure actions stay on screen). */
export async function runAnalysis<T>(o: RunOptions<T>): Promise<boolean> {
  const line = h("p", { class: "status muted", role: "status" }, o.message);
  const actions = h("div", { class: "run-actions" });
  o.host.replaceChildren(line, actions);
  let takeId: string | null = null;
  let url: string | null = null;

  const attempt = async (fn: () => Promise<T>): Promise<boolean> => {
    actions.replaceChildren();
    line.textContent = o.message;
    line.classList.remove("warn");
    try {
      const result = await fn();
      lastFailed = null;
      if (url) URL.revokeObjectURL(url);
      o.open(result);
      if (o.host.isConnected) o.goToReport();
      return true;
    } catch (err) {
      const reason = err instanceof ApiError ? err.detail : (err as Error).message;
      takeId = (err instanceof ApiError ? err.takeId : null) ?? takeId;
      lastFailed = { blob: o.blob, filename: o.filename, takeId, error: reason };
      line.textContent = `Analysis failed: ${reason}. ` + (takeId
        ? "Your recording is saved on this computer and listed under Takes."
        : "Your recording is still in this page; download it or try again.");
      line.classList.add("warn");
      url = url ?? URL.createObjectURL(o.blob);
      actions.replaceChildren(
        h("button", { class: "primary", type: "button", onClick: () => void attempt(() => (takeId ? o.retry(takeId) : o.start())) }, "Retry"),
        h("a", { class: "ghost-btn", href: url, download: downloadName(o.filename) }, "Download recording"),
      );
      if (o.onAbandon) actions.append(h("button", { class: "ghost-btn", type: "button", onClick: () => o.onAbandon?.() }, "Start over"));
      return false;
    }
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
