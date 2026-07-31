import type { Document, PlanListItem, Quiz, AnswersState, Content, GradingResult } from "./types";

/**
 * 后端 API 基址。
 * - 网页端: 留空 -> "/api" (相对路径, 浏览器同源, 由 nginx 反代到后端)。
 * - App 端: 构建时注入 VITE_API_BASE 为服务器绝对地址 (如 "http://<ip>/api"),
 *   否则 Capacitor WebView 里 /api 会解析到设备本地 origin 而非服务器。
 * 末尾斜杠会被去掉, 保证 "/api" 与 "http://x/api/" 拼接路径都不出现双斜杠。
 */
const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/+$/, "");

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + url, init);
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
    const res = await fetch(`${API_BASE}/plans/${planId}/modules/${moduleId}/content`, {
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
