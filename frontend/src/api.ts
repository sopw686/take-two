import type { Analysis, CompareResult, Health, Settings, SuggestResponse, TakeSummary } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<Health>(r)),
  sample: () => fetch("/api/sample").then((r) => j<{ text: string }>(r)),
  async createTake(audio: Blob, filename: string, script: string, settings: Settings, label = ""): Promise<Analysis> {
    const fd = new FormData();
    fd.append("audio", audio, filename);
    fd.append("script", script);
    fd.append("settings", JSON.stringify(settings));
    fd.append("label", label);
    return fetch("/api/takes", { method: "POST", body: fd }).then((r) => j<Analysis>(r));
  },
  reanalyze: (takeId: string, script: string, settings: Settings) =>
    fetch(`/api/takes/${takeId}/reanalyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, settings }),
    }).then((r) => j<Analysis>(r)),
  listTakes: () => fetch("/api/takes").then((r) => j<TakeSummary[]>(r)),
  getTake: (id: string) => fetch(`/api/takes/${id}`).then((r) => j<Analysis>(r)),
  suggest: (script: string, goal: string, notes: string, targetSeconds: number | null) =>
    fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, goal, notes, target_seconds: targetSeconds }),
    }).then((r) => j<SuggestResponse>(r)),
  applySuggestions: (script: string, accepted: unknown[]) =>
    fetch("/api/suggest/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, accepted }),
    }).then((r) => j<{ text: string }>(r)),
  coach: (takeId: string) => fetch(`/api/takes/${takeId}/coach`, { method: "POST" }).then((r) => j<Analysis>(r)),
  compare: (takeId: string) => fetch(`/api/compare?take_id=${encodeURIComponent(takeId)}`).then((r) => j<CompareResult>(r)),
};
