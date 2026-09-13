import type { ChatTurn, Document, PlanListItem, Quiz, AnswersState, Content, GradingResult, ImaSettings, ImaSettingsUpdate, GenSettings, GenSettingsUpdate, ModelSettings, ModelSettingsUpdate, UsageSummary, Annotation, BookmarkItem, MemoryItem, MemoryProfile, MemorySettings, MemorySettingsUpdate, SaveToImaRequest, SaveToImaResponse, User, AuthResponse, AdminUserCreateInput } from "./types";

/**
 * 后端 API 基址。
 * - 网页端: 留空 -> "/api" (相对路径, 浏览器同源, 由 nginx 反代到后端)。
 * - App 端: 构建时注入 VITE_API_BASE 为服务器绝对地址 (如 "http://<ip>/api"),
 *   否则 Capacitor WebView 里 /api 会解析到设备本地 origin 而非服务器。
 * 末尾斜杠会被去掉, 保证 "/api" 与 "http://x/api/" 拼接路径都不出现双斜杠。
 */
const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/+$/, "");

// ---------------------------------------------------------------------------
// 会话存储（双 token: access JWT + refresh opaque）与 401 自动刷新
// ---------------------------------------------------------------------------

const TOKEN_KEY = "zhixue_token";
const REFRESH_KEY = "zhixue_refresh";
const USER_KEY = "zhixue_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

function saveSession(access: string, refresh: string, user: User) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

/** 会话失效后的统一出口：清掉本地状态并回到登录页。 */
function redirectToLogin() {
  clearSession();
  if (!window.location.pathname.startsWith("/login")) {
    window.location.assign("/login");
  }
}

// 单飞刷新：并发请求共享同一次 /auth/refresh，成功后各自重放原请求。
let refreshPromise: Promise<boolean> | null = null;

async function performRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const body = (await res.json()) as AuthResponse;
    saveSession(body.access_token, body.refresh_token, body.user);
    return true;
  } catch {
    return false;
  }
}

async function tryRefresh(): Promise<boolean> {
  refreshPromise ??= performRefresh().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** 从错误响应体中提取后端的 detail 信息（FastAPI 返回 {"detail": "..."}），
 *  让流式请求失败时也能显示具体原因，而不是干巴巴的 "HTTP 503"。 */
async function httpError(res: Response): Promise<Error> {
  const raw = await res.text().catch(() => "");
  let msg = raw;
  try {
    const body = JSON.parse(raw);
    if (typeof body?.detail === "string") msg = body.detail;
  } catch {
    // 非 JSON 响应体, 保留原文
  }
  return new Error(msg || `HTTP ${res.status}`);
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + url, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
  });
  if (res.status === 401) {
    // access token 过期 -> 无感刷新后重放一次；再失败则回登录页。
    if (await tryRefresh()) return json<T>(url, init);
    redirectToLogin();
    throw new Error("登录已过期，请重新登录");
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/** SSE 长任务 (测验生成/批改/计划创建): 后端生成期间每 30s 发 ": ping" 注释帧
 *  保活, 注释帧被解析器自然忽略; done 事件返回最终数据, error 事件抛出。
 *  init 可携带 body 等请求参数 (与 auth 头合并)。 */
async function sseTask<T>(url: string, init?: RequestInit): Promise<T> {
  const doFetch = () =>
    fetch(`${API_BASE}${url}`, {
      method: "POST",
      ...init,
      headers: {
        ...(init?.headers as Record<string, string> | undefined),
        ...authHeaders(),
      },
    });
  let res = await doFetch();
  if (res.status === 401) {
    if (await tryRefresh()) res = await doFetch();
    else {
      redirectToLogin();
      throw new Error("登录已过期，请重新登录");
    }
  }
  if (!res.ok) throw await httpError(res);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneData: T | null = null;
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
        // ": ping" 注释帧没有 data 行, 自然跳过
      }
      if (!dataStr) continue;
      const data = JSON.parse(dataStr);
      if (eventType === "done") doneData = data as T;
      else if (eventType === "error") errMsg = data.detail;
    }
  }

  if (errMsg) throw new Error(errMsg);
  if (doneData === null) throw new Error("stream ended without done event");
  return doneData;
}

export const api = {
  health: () => json<{ configured: boolean; model: string }>("/health"),

  // ----- auth -----

  login: async (username: string, password: string): Promise<AuthResponse> => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    const auth = body as AuthResponse;
    saveSession(auth.access_token, auth.refresh_token, auth.user);
    return auth;
  },

  /** 登出：尽力吊销服务端 refresh token，然后清空本地会话。 */
  logout: async () => {
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (refresh) {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      }).catch(() => {});
    }
    clearSession();
  },

  getMe: () => json<User>("/auth/me"),

  /** 修改自己的密码；后端会吊销该用户全部 refresh token。 */
  changePassword: (oldPassword: string, newPassword: string) =>
    json<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  // ----- admin（用户管理）-----

  listUsers: () => json<User[]>("/admin/users"),

  createUser: (data: AdminUserCreateInput) =>
    json<User>("/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  deleteUser: (id: string) =>
    json<{ deleted: string }>(`/admin/users/${id}`, { method: "DELETE" }),

  resetUserPassword: (id: string, newPassword: string) =>
    json<{ ok: boolean }>(`/admin/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    }),

  // ----- plans -----

  listPlans: (q?: string) =>
    json<PlanListItem[]>(`/plans${q ? `?q=${encodeURIComponent(q)}` : ""}`),

  // 首页计划列表拖拽排序：按新顺序提交当前用户的全部计划 id
  reorderPlans: (planIds: string[]) =>
    json<PlanListItem[]>(`/plans/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ planIds }),
    }),

  getPlan: (id: string) => json<Document>(`/plans/${id}`),

  // 计划创建是分钟级长任务: 走 SSE + 心跳保活, 否则移动网络会掐断空闲连接
  // 报超时/失败 (而后端其实已生成入库)。
  createPlan: (input: string, mode: "topic" | "materials") =>
    sseTask<Document>("/plans/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input, mode }),
    }),

  deletePlan: (id: string) =>
    json<{ deleted: string }>(`/plans/${id}`, { method: "DELETE" }),

  // 测验生成/批改是分钟级长任务, 走 SSE + 30s 心跳, 避免移动网络/nginx
  // 掐断无数据回传的连接 (Failed to fetch); 返回值仍是完整 Document。
  generateQuiz: (planId: string, moduleId: string) =>
    sseTask<Document>(`/plans/${planId}/modules/${moduleId}/quiz`),

  getQuiz: (planId: string, moduleId: string) =>
    json<Quiz>(`/plans/${planId}/modules/${moduleId}/quiz`),

  getContent: (planId: string, moduleId: string) =>
    json<Content>(`/plans/${planId}/modules/${moduleId}/content`),

  // 手工编辑学习内容正文（只改 markdown，关键要点不变），返回完整 Document
  updateContent: (planId: string, moduleId: string, markdown: string) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}/content`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown }),
    }),

  // 书签列表：当前用户跨计划/模块的全部书签
  listBookmarks: () => json<BookmarkItem[]>(`/annotations`),

  // 长期记忆（Mem0）：列表 / 编辑 / 删除 / 总开关 / 学生画像
  listMemories: () => json<MemoryItem[]>(`/memories`),

  updateMemory: (memoryId: string, memory: string) =>
    json<{ updated: string }>(`/memories/${memoryId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory }),
    }),

  deleteMemory: (memoryId: string) =>
    json<{ deleted: string }>(`/memories/${memoryId}`, { method: "DELETE" }),

  getMemoryProfile: () => json<MemoryProfile>(`/memories/profile`),

  updateMemoryProfile: (profile: string) =>
    json<MemoryProfile>(`/memories/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile }),
    }),

  getMemorySettings: () => json<MemorySettings>("/settings/memory"),

  updateMemorySettings: (data: MemorySettingsUpdate) =>
    json<MemorySettings>("/settings/memory", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  saveAnswers: (planId: string, moduleId: string, answers: Record<string, string>) =>
    json<Document>(`/plans/${planId}/modules/${moduleId}/answers`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    }),

  getAnswers: (planId: string, moduleId: string) =>
    json<AnswersState>(`/plans/${planId}/modules/${moduleId}/answers`),

  gradeQuiz: (planId: string, moduleId: string) =>
    sseTask<Document>(`/plans/${planId}/modules/${moduleId}/grade`),

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
    const doFetch = () =>
      fetch(`${API_BASE}/plans/${planId}/modules/${moduleId}/content`, {
        method: "POST",
        headers: authHeaders(),
      });
    let res = await doFetch();
    if (res.status === 401) {
      if (await tryRefresh()) res = await doFetch();
      else {
        redirectToLogin();
        throw new Error("登录已过期，请重新登录");
      }
    }
    if (!res.ok) throw await httpError(res);

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

  getImaSettings: () =>
    json<ImaSettings>("/settings/ima"),

  updateImaSettings: (data: ImaSettingsUpdate) =>
    json<ImaSettings>("/settings/ima", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  getRegenSettings: () =>
    json<GenSettings>("/settings/regenerate"),

  updateRegenSettings: (data: GenSettingsUpdate) =>
    json<GenSettings>("/settings/regenerate", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  getModelSettings: () =>
    json<ModelSettings>("/settings/model"),

  updateModelSettings: (data: ModelSettingsUpdate) =>
    json<ModelSettings>("/settings/model", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  getUsageSummary: () => json<UsageSummary>("/usage/summary"),

  listAnnotations: (planId: string, moduleId: string) =>
    json<Annotation[]>(`/plans/${planId}/modules/${moduleId}/annotations`),

  createAnnotation: (
    planId: string,
    moduleId: string,
    data: { quote: string; prefix: string; suffix: string; note: string },
  ) =>
    json<Annotation>(`/plans/${planId}/modules/${moduleId}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  updateAnnotation: (planId: string, annotationId: string, note: string) =>
    json<Annotation>(`/plans/${planId}/annotations/${annotationId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),

  deleteAnnotation: (planId: string, annotationId: string) =>
    json<{ deleted: string }>(`/plans/${planId}/annotations/${annotationId}`, {
      method: "DELETE",
    }),

  saveToIma: (planId: string, data: SaveToImaRequest = {}) =>
    json<SaveToImaResponse>(`/plans/${planId}/save-to-ima`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  /** SSE stream for the coach chat. onDelta for text tokens, onTool for
   *  create_plan / search_plans tool events. Resolves on done, throws on error. */
  streamCoach: async (
    goal: string,
    history: ChatTurn[],
    onDelta: (text: string) => void,
    onTool: (data: { phase: string; name: string; output?: string }) => void,
  ): Promise<void> => {
    const doFetch = () =>
      fetch(`${API_BASE}/coach/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ goal, history }),
      });
    let res = await doFetch();
    if (res.status === 401) {
      if (await tryRefresh()) res = await doFetch();
      else {
        redirectToLogin();
        throw new Error("登录已过期，请重新登录");
      }
    }
    if (!res.ok) throw await httpError(res);

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
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
        if (eventType === "delta") onDelta(data.text);
        else if (eventType === "tool") onTool(data);
        else if (eventType === "error") errMsg = data.detail;
      }
    }

    if (errMsg) throw new Error(errMsg);
  },
};
