import type { Analysis, CompareResult, Health, ImprovAnalysis, JobStatus, Question, QuestionsResponse, Settings, SuggestResponse, TakeSummary, Topic } from "./types";

/** A failed request. takeId is set when the server kept a take folder that can be retried. */
export class ApiError extends Error {
  constructor(readonly detail: string, readonly status: number, readonly takeId: string | null = null) {
    super(`${status}: ${detail}`);
  }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    let takeId: string | null = null;
    try {
      const body = await r.json();
      const d = body.detail;
      if (typeof d === "string") detail = d;
      else if (Array.isArray(d)) detail = d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join("; ");
      else if (d && typeof d === "object") {
        detail = d.message ?? JSON.stringify(d);
        takeId = d.take_id ?? null;
      } else detail = JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, r.status, takeId);
  }
  return r.json() as Promise<T>;
}

function takeForm(audio: Blob, filename: string, fields: Record<string, string>, settings: Settings): FormData {
  const fd = new FormData();
  fd.append("audio", audio, filename);
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  fd.append("settings", JSON.stringify(settings));
  return fd;
}

const post = (url: string, body?: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

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
  reanalyze: (takeId: string, script: string | null, settings: Settings) =>
    fetch(`/api/takes/${takeId}/reanalyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(script === null ? { settings } : { script, settings }),
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
  getAnyTake: (id: string) => fetch(`/api/takes/${id}`).then((r) => j<Analysis | ImprovAnalysis>(r)),
  improvTopics: () => fetch("/api/improv/topics").then((r) => j<{ categories: string[]; topics: Topic[] }>(r)),
  async createImprov(audio: Blob, filename: string, topic: string, goalS: number | null, content: boolean, settings: Settings,
    label = ""): Promise<ImprovAnalysis> {
    const fd = new FormData();
    fd.append("audio", audio, filename);
    fd.append("topic", topic);
    if (goalS !== null) fd.append("goal_s", String(goalS));
    fd.append("content", String(content));
    fd.append("settings", JSON.stringify(settings));
    fd.append("label", label);
    return fetch("/api/improv", { method: "POST", body: fd }).then((r) => j<ImprovAnalysis>(r));
  },
  reanalyzeImprov: (takeId: string, settings: Settings) =>
    fetch(`/api/improv/${takeId}/reanalyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    }).then((r) => j<ImprovAnalysis>(r)),
  coachImprov: (takeId: string, content?: boolean) =>
    fetch(`/api/improv/${takeId}/coach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(content === undefined ? {} : { content }),
    }).then((r) => j<ImprovAnalysis>(r)),
  retryTake: (takeId: string, body: { script?: string; settings?: Settings } = {}) =>
    post(`/api/takes/${takeId}/retry`, body).then((r) => j<Analysis | ImprovAnalysis>(r)),
  deleteTake: (takeId: string) => fetch(`/api/takes/${takeId}`, { method: "DELETE" }).then((r) => j<{ deleted: string }>(r)),
  loadExample: (settings: Settings, name = "coral") => post(`/api/examples/${name}`, { settings }).then((r) => j<Analysis>(r)),
  /** Background analysis with progress: these return at once with the job; poll job(takeId). */
  startTakeJob: (audio: Blob, filename: string, script: string, settings: Settings, label = "") =>
    fetch("/api/jobs/takes", { method: "POST", body: takeForm(audio, filename, { script, label }, settings) }).then((r) => j<JobStatus>(r)),
  startImprovJob: (audio: Blob, filename: string, topic: string, goalS: number | null, content: boolean, settings: Settings, label = "",
    question: Question | null = null) =>
    fetch("/api/jobs/improv", { method: "POST", body: takeForm(audio, filename,
      { topic, content: String(content), label, ...(goalS !== null ? { goal_s: String(goalS) } : {}),
        ...(question ? { question: JSON.stringify(question) } : {}) }, settings) }).then((r) => j<JobStatus>(r)),
  improvQuestions: (script: string) => post("/api/improv/questions", { script }).then((r) => j<QuestionsResponse>(r)),
  startDrillJob: (parentId: string, audio: Blob, filename: string, kind: "line" | "section", index: number, settings: Settings) =>
    fetch(`/api/jobs/drill/${parentId}`, { method: "POST", body: takeForm(audio, filename, { kind, index: String(index) }, settings) })
      .then((r) => j<JobStatus>(r)),
  startRetryJob: (takeId: string, body: { script?: string; settings?: Settings } = {}) =>
    post(`/api/jobs/retry/${takeId}`, body).then((r) => j<JobStatus>(r)),
  job: (takeId: string) => fetch(`/api/jobs/${takeId}`).then((r) => j<JobStatus>(r)),
  compare: (takeId: string) => fetch(`/api/compare?take_id=${encodeURIComponent(takeId)}`).then((r) => j<CompareResult>(r)),
};
