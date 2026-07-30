import type { Document, PlanListItem, Quiz, AnswersState, Content, GradingResult } from "./types";

const API_BASE_KEY = "zhixue_api_base";
const API_BASE_HISTORY_KEY = "zhixue_api_base_history";
const HISTORY_MAX = 10;

/** 默认后端地址（含 /api）。未在 localStorage / VITE_API_BASE 覆盖时使用。 */
export const DEFAULT_API_BASE = "/api";

/** 预设环境，下拉选择时展示。本地为默认。 */
export interface ApiEnv {
  label: string;
  url: string;
}

export const PRESET_ENVS: ApiEnv[] = [
  { label: "本地", url: "/api" },
];

export function getApiBase(): string {
  return localStorage.getItem(API_BASE_KEY) || import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;
}

/** 设置当前后端地址；非空时同时记入历史（便于下次下拉选择）。 */
export function setApiBase(url: string): void {
  const trimmed = url.trim();
  if (trimmed) {
    localStorage.setItem(API_BASE_KEY, trimmed);
    addApiBaseHistory(trimmed);
  } else {
    localStorage.removeItem(API_BASE_KEY);
  }
}

/** 已保存的后端地址历史（最近优先，去重）。 */
export function getApiBaseHistory(): string[] {
  try {
    const raw = localStorage.getItem(API_BASE_HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? (arr.filter((x) => typeof x === "string") as string[]) : [];
  } catch {
    return [];
  }
}

export function addApiBaseHistory(url: string): void {
  const trimmed = url.trim();
  if (!trimmed) return;
  const next = [trimmed, ...getApiBaseHistory().filter((u) => u !== trimmed)].slice(0, HISTORY_MAX);
  localStorage.setItem(API_BASE_HISTORY_KEY, JSON.stringify(next));
}

export function removeApiBaseHistory(url: string): void {
  const next = getApiBaseHistory().filter((u) => u !== url);
  localStorage.setItem(API_BASE_HISTORY_KEY, JSON.stringify(next));
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(getApiBase() + url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => json<{ configured: boolean; model: string }>("/health"),

  listPlans: () => json<PlanListItem[]>("/plans"),

  getPlan: (id: string) => json<Document>(`/plans/${id}`),

  createPlan: (input: string, mode: "topic" | "materials") =>
    json<Document>("/plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input, mode }),
    }),

  deletePlan: (id: string) =>
    json<{ deleted: string }>(`/plans/${id}`, { method: "DELETE" }),

  generateQuiz: (planId: string, moduleId: string) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}/quiz`, { method: "POST" }),

  getQuiz: (planId: string, moduleId: string) =>
    json<Quiz>(`/plans/${planId}/modules/${moduleId}/quiz`),

  getContent: (planId: string, moduleId: string) =>
    json<Content>(`/plans/${planId}/modules/${moduleId}/content`),

  saveAnswers: (planId: string, moduleId: string, answers: Record<string, string>) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}/answers`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    }),

  getAnswers: (planId: string, moduleId: string) =>
    json<AnswersState>(`/plans/${planId}/modules/${moduleId}/answers`),

  gradeQuiz: (planId: string, moduleId: string) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}/grade`, { method: "POST" }),

  patchModule: (planId: string, moduleId: string, status: string) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),

  /** SSE stream for content generation. Calls onDelta for each token chunk. */
  streamContent: async (
    planId: string,
    moduleId: string,
    onDelta: (text: string) => void,
  ): Promise<Document> => {
    const res = await fetch(`${getApiBase()}/plans/${planId}/modules/${moduleId}/content`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let doneDoc: Document | null = null;
    let errMsg: string | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";

      for (const frame of frames) {
        let eventType = "";
        let dataStr = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) eventType = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataStr += line.slice(6);
        }
        if (!dataStr) continue;
        const data = JSON.parse(dataStr);
        if (eventType === "delta") onDelta(data.delta);
        else if (eventType === "done") doneDoc = data as Document;
        else if (eventType === "error") errMsg = data.detail;
      }
    }

    if (errMsg) throw new Error(errMsg);
    if (!doneDoc) throw new Error("stream ended without done event");
    return doneDoc;
  },
};
