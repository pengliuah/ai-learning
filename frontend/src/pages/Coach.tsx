import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, Send, Loader2, AlertCircle, ArrowRight, ClipboardList,
  Search, Trash2, Copy, Check, Bookmark, Brain, X, Paperclip, FileText,
} from "lucide-react";
import { Markdown } from "../components/Markdown";
import { AttachmentList, useAttachmentManager } from "../components/Attachments";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ChatTurn, PlanListItem, SaveToImaResponse } from "../api/types";

const TOOL_LABELS: Record<string, string> = {
  create_plan: "制定计划",
  search_plans: "搜索计划",
  archive_content: "存档内容",
};

interface ToolEvent {
  name: string;
  phase: "start" | "end";
  data?: { topic?: string; content?: string } | PlanListItem[];
  note?: string;
  archiveResult?: "memory" | "ima" | "failed";
  archiveError?: string;
  dismissed?: boolean;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: string;
  tools?: ToolEvent[];
  /** 本条用户消息附带的文件名（展示用，id 不持久化——转写在服务端） */
  attNames?: string[];
}

const EXAMPLES = [
  "帮我制定 Python 装饰器的学习计划",
  "有没有机器学习的学习计划",
  "讲解一下闭包的概念",
];

/** 聊天历史按用户隔离：不同账号互不可见。 */
function storageKey(userId: string | undefined) {
  return userId ? `zhixue_coach_messages_${userId}` : "zhixue_coach_messages_anonymous";
}

function summaryKey(userId: string | undefined) {
  return userId ? `zhixue_coach_summary_${userId}` : "zhixue_coach_summary_anonymous";
}

interface SummaryState {
  summary: string;
  count: number;
}

function loadSummary(userId: string | undefined): SummaryState {
  try {
    const raw = localStorage.getItem(summaryKey(userId));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (typeof parsed?.summary === "string") return { summary: parsed.summary, count: parsed.count || 0 };
    }
  } catch {}
  return { summary: "", count: 0 };
}

function saveSummary(userId: string | undefined, st: SummaryState) {
  try {
    localStorage.setItem(summaryKey(userId), JSON.stringify(st));
  } catch {}
}

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/** 同一条回复里模型可能换关键词连续调用 search_plans，每次都渲染一张卡会堆满屏幕。
 *  收敛成一张：保留最后一次的结果，被合并的次数放进提示文案。 */
/** 存档内容 = 当前消息之前最近一条有正文的助手回复（原样，不经整理）。 */
/** 存档候选: 当前消息之前所有有正文的教练回复, 新的在前, 最多 5 条。
 *  默认选中最近一条"有分量"的 (>=120 字), 跳过"好的/要不要我…"这类短确认/反问——
 *  机械取"上一条"会存进反问句而不是用户要的内容。 */
const ARCHIVE_MIN_SUBSTANTIVE = 120;

function assistantReplyCandidates(messages: Message[], current: Message): string[] {
  const idx = messages.indexOf(current);
  const out: string[] = [];
  for (let i = idx - 1; i >= 0 && out.length < 5; i--) {
    const m = messages[i];
    if (m.role === "assistant" && m.content.trim()) out.push(m.content);
  }
  return out;
}

function defaultArchivePick(candidates: string[]): number {
  const i = candidates.findIndex((c) => c.length >= ARCHIVE_MIN_SUBSTANTIVE);
  return i === -1 ? 0 : i;
}

function coalesceSearchTools(tools: ToolEvent[]): ToolEvent[] {
  const ends = tools
    .map((t, i) => ({ t, i }))
    .filter(({ t }) => t.name === "search_plans" && t.phase === "end");
  if (ends.length <= 1) return tools;
  const last = ends[ends.length - 1];
  const dropped = ends.slice(0, -1);
  const droppedEmpty = dropped.filter(
    ({ t }) => !Array.isArray(t.data) || t.data.length === 0,
  ).length;
  const kept: ToolEvent = {
    ...last.t,
    note:
      Array.isArray(last.t.data) && last.t.data.length > 0
        ? `已合并此前 ${dropped.length} 次未命中的检索`
        : droppedEmpty > 0
          ? `共检索 ${ends.length} 次，均未找到相关的学习计划`
          : undefined,
  };
  const merged = new Map<number, ToolEvent>();
  tools.forEach((t, i) => merged.set(i, t));
  merged.set(last.i, kept);
  dropped.forEach(({ i }) => merged.delete(i));
  return [...merged.values()];
}

/** 聊天存档卡片：模型识别到「存档/保存/记住」意图后出现。
 *  内容 = 上一条回复的原文（不经过模型整理），宽度贴近对话列，完整展示。 */
function ArchiveCard({
  candidates,
  result,
  onResult,
  onDismiss,
}: {
  candidates: string[];
  result?: ToolEvent["archiveResult"];
  onResult?: (result: Exclude<ToolEvent["archiveResult"], undefined>, detail?: string) => void;
  onDismiss?: () => void;
}) {
  const [state, setState] = useState<"idle" | "saving" | "memory" | "ima" | "failed">(
    result === "memory" ? "memory" : result === "ima" ? "ima" : "idle",
  );
  const [error, setError] = useState("");
  const [pick, setPick] = useState(() => defaultArchivePick(candidates));
  const content = candidates[pick] ?? "";
  if (!content.trim()) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 px-4 py-3 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
        没有找到可存档的教练回复
      </div>
    );
  }

  const run = async (target: "memory" | "ima") => {
    setState("saving");
    setError("");
    try {
      if (target === "memory") await api.archiveToMemory(content);
      else await api.archiveToIma(content);
      setState(target);
      onResult?.(target);
    } catch (e) {
      const detail = (e as Error).message || "保存失败";
      setError(detail);
      setState("failed");
      onResult?.("failed", detail);
    }
  };

  if (state === "memory") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
        <Check className="h-4 w-4 shrink-0" />
        已保存到长期记忆（记忆页可查看/编辑）
      </div>
    );
  }
  if (state === "ima") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
        <Check className="h-4 w-4 shrink-0" />
        已保存为 IMA 笔记
      </div>
    );
  }
  const failed = state === "failed";
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-800 dark:bg-indigo-900/30">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {candidates.length > 1 && state === "idle" && (
            <select
              value={pick}
              onChange={(e) => setPick(Number(e.target.value))}
              aria-label="选择要存档的回复"
              className="mb-2 w-full max-w-full rounded-md border border-indigo-200 bg-white px-2 py-1 text-xs text-gray-600 dark:border-indigo-700 dark:bg-gray-800 dark:text-gray-300"
            >
              {candidates.map((c, i) => (
                <option key={i} value={i}>
                  {i === pick ? "✓ " : ""}
                  {c.replace(/\s+/g, " ").slice(0, 40)}
                  {c.length > 40 ? "…" : ""}
                </option>
              ))}
            </select>
          )}
          <p className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-800 dark:text-gray-100">
            {content}
          </p>
        </div>
        <button
          onClick={onDismiss}
          aria-label="取消存档"
          title="取消存档"
          className="shrink-0 rounded p-1 text-gray-400 hover:bg-indigo-100 hover:text-gray-600 dark:hover:bg-indigo-900/40 dark:hover:text-gray-300"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => run("memory")}
          disabled={state === "saving"}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          <Brain className="h-4 w-4" />
          保存到长期记忆
        </button>
        <button
          onClick={() => run("ima")}
          disabled={state === "saving"}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          <Bookmark className="h-4 w-4" />
          保存到 IMA
        </button>
        {state === "saving" && (
          <span className="inline-flex items-center text-xs text-indigo-400">
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            保存中...
          </span>
        )}
        {(error || failed) && (
          <span className="inline-flex items-center text-xs text-red-500">
            {failed && "保存失败，可重试；"}
            {error}
          </span>
        )}
      </div>
    </div>
  );
}

function ToolCard({
  tool,
  navigate,
  archiveCandidates = [],
  archiveResult,
  archiveError,
  onArchiveResult,
  onDismiss,
}: {
  tool: ToolEvent;
  navigate: ReturnType<typeof useNavigate>;
  archiveCandidates?: string[];
  archiveResult?: ToolEvent["archiveResult"];
  archiveError?: string;
  onArchiveResult?: (result: Exclude<ToolEvent["archiveResult"], undefined>, detail?: string) => void;
  onDismiss?: () => void;
}) {
  const label = TOOL_LABELS[tool.name] || tool.name;
  if (tool.phase === "start") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在{label}...
      </div>
    );
  }
  if (tool.name === "archive_content") {
    if (tool.dismissed) return null;
    return (
      <ArchiveCard
        candidates={archiveCandidates}
        result={archiveResult}
        onResult={onArchiveResult}
        onDismiss={onDismiss}
      />
    );
  }
  if (tool.name === "create_plan" && tool.data && typeof tool.data === "object" && !Array.isArray(tool.data)) {
    const d = tool.data as { topic?: string };
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 dark:border-indigo-800 dark:bg-indigo-900/30">
        <ClipboardList className="h-4 w-4 shrink-0 text-indigo-500 dark:text-indigo-400" />
        <span className="text-sm text-indigo-700 dark:text-indigo-300">想要制定「{d.topic}」的学习计划？</span>
        <button
          onClick={() => navigate(`/plans/new?topic=${encodeURIComponent(d.topic || "")}`)}
          className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          制定计划
          <ArrowRight className="h-3 w-3" />
        </button>
      </div>
    );
  }
  if (tool.name === "search_plans" && Array.isArray(tool.data)) {
    const results = tool.data as PlanListItem[];
    if (results.length === 0) {
      return (
        <div className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-700 dark:border-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300">
          <Search className="h-4 w-4 shrink-0" />
          {tool.note || "没有找到相关的学习计划"}
        </div>
      );
    }
    return (
      <div className="w-72 max-w-full rounded-lg border border-gray-200 bg-gray-50 p-2 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-1.5 px-1 pb-1.5 text-xs text-gray-500 dark:text-gray-400">
          <Search className="h-3.5 w-3.5" />
          找到 {results.length} 个计划
          {tool.note && <span className="ml-1">（{tool.note}）</span>}
        </div>
        <div className="space-y-1">
          {results.map((p) => (
            <div key={p.id} className="flex items-center gap-2 rounded-md bg-white px-2 py-1.5 dark:bg-gray-700">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-gray-800 dark:text-gray-200">{p.title}</p>
                <p className="text-xs text-gray-400">{Math.round(p.progress * 100)}%</p>
              </div>
              <button
                onClick={() => navigate(`/plans/${p.id}`)}
                className="inline-flex shrink-0 items-center gap-0.5 rounded-md bg-indigo-600 px-2 py-1 text-xs font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
              >
                查看
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return null;
}

export function Coach() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const stored = localStorage.getItem(storageKey(user?.id));
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const attachments = useAttachmentManager();
  const coachFileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 仅当用户贴近底部时才自动跟随流式滚动，上滑查看历史时不抢滚动条
  const stickToBottom = useRef(true);

  const onMessagesScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  }, []);

  useEffect(() => {
    if (!stickToBottom.current) return;
    const el = scrollRef.current;
    if (!el) return;
    // 流式过程用瞬时定位，避免 smooth 与内容增高互相抢滚动条
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(user?.id), JSON.stringify(messages));
    } catch {}
  }, [messages, user?.id]);

  // Auto-send a prefilled goal from ?goal= query param.
  const [searchParams, setSearchParams] = useSearchParams();
  const autoSent = useRef(false);
  const [summaryState, setSummaryState] = useState<SummaryState>(() =>
    loadSummary(user?.id),
  );
  useEffect(() => {
    saveSummary(user?.id, summaryState);
  }, [summaryState, user?.id]);
  useEffect(() => {
    const goal = searchParams.get("goal");
    if (goal && !autoSent.current) {
      autoSent.current = true;
      setSearchParams({}, { replace: true });
      handleSend(goal);
    }
  }, [searchParams]);

  const copyUserMessage = async (m: Message) => {
    try {
      await navigator.clipboard.writeText(m.content);
      setInput(m.content);
      setCopiedId(m.id);
      setTimeout(() => setCopiedId((id) => (id === m.id ? null : id)), 1500);
    } catch {
      // clipboard 不可用时仍填入输入框，方便再次发送
      setInput(m.content);
    }
  };

  // 把存档结果写回对应消息的工具条目 (随 localStorage 持久化, 刷新后仍是完成/失败态)
  const updateToolState = (
    messageId: string,
    toolRef: ToolEvent,
    patch: Partial<ToolEvent>,
  ) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              tools: (msg.tools || []).map((t) => (t === toolRef ? { ...t, ...patch } : t)),
            }
          : msg,
      ),
    );
  };

  const handleSend = async (text?: string) => {
    const goal = (text ?? input).trim();
    // 允许"只发附件不打字"——goal 缺省用一句引导语, 后端把资料转写拼进上下文
    const attIds = attachments.readyIds;
    if ((!goal && attIds.length === 0) || streaming) return;
    if (attachments.hasActive) return; // 还有文件在解析/上传, 等就绪再发

    const attNames = attachments.items
      .filter((it) => attIds.includes(it.att.id))
      .map((it) => it.att.filename);

    const assistantId = uid();
    setInput("");
    setSelectedUserId(null);
    setStreaming(true);
    stickToBottom.current = true;
    setMessages((prev) => [
      ...prev,
      {
        id: uid(),
        role: "user",
        content: goal || `（发送了 ${attIds.length} 个学习资料文件）`,
        attNames: attNames.length ? attNames : undefined,
      },
      { id: assistantId, role: "assistant", content: "", tools: [] },
    ]);
    attachments.detach(attIds);

    const history: ChatTurn[] = messages
      .filter((m) => m.content && !m.error)
      .map((m) => ({ role: m.role, content: m.content }));

    try {
      await api.streamCoach(
        goal,
        history,
        (delta) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + delta } : m,
            ),
          );
        },
        (data) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m;
              const tools = [...(m.tools || [])];
              if (data.phase === "start") {
                tools.push({ name: data.name, phase: "start" });
              } else {
                let parsed: ToolEvent["data"];
                try {
                  parsed = JSON.parse(data.output || "");
                } catch {
                  parsed = undefined;
                }
                for (let i = tools.length - 1; i >= 0; i--) {
                  if (tools[i].name === data.name && tools[i].phase === "start") {
                    tools[i] = { ...tools[i], phase: "end", data: parsed };
                    break;
                  }
                }
              }
              return { ...m, tools };
            }),
          );
        },
        (data) => setSummaryState({ summary: data.summary, count: data.count }),
        summaryState.summary || summaryState.count
          ? { summary: summaryState.summary, count: summaryState.count }
          : undefined,
        attIds,
      );
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, error: (e as Error).message } : m,
        ),
      );
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="mx-auto mb-3 flex w-full max-w-5xl shrink-0 items-center gap-3 px-4 pt-4">
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回
        </button>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI 教练</h1>
        <button
          onClick={() => {
            if (confirm("清除所有聊天历史？")) {
              setMessages([]);
              setSummaryState({ summary: "", count: 0 });
            }
          }}
          disabled={streaming || messages.length === 0}
          className="ml-auto inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
        >
          <Trash2 className="h-4 w-4" />
          清除历史
        </button>
      </div>

      {/* Messages —— 唯一滚动区（通栏，滚动条贴窗口边缘；内容居中限宽） */}
      <div
        ref={scrollRef}
        onScroll={onMessagesScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-4">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              输入学习目标，AI 教练将与你对话
            </p>
            <div className="flex flex-col gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => handleSend(ex)}
                  className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:border-indigo-300 hover:text-indigo-600 dark:border-gray-700 dark:text-gray-300 dark:hover:border-indigo-600 dark:hover:text-indigo-400"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.length > 0 && (
          <div className="mx-auto w-full max-w-5xl space-y-4 px-4 py-2">
            {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
            {m.role === "user" ? (
              <div className={["relative max-w-[80%]", selectedUserId === m.id && "mb-8"].filter(Boolean).join(" ")}>
                <button
                  type="button"
                  onClick={() =>
                    setSelectedUserId((id) => (id === m.id ? null : m.id))
                  }
                  className={[
                    "w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-left text-sm text-white",
                    selectedUserId === m.id && "ring-2 ring-indigo-300 ring-offset-1 dark:ring-offset-gray-900",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {m.attNames && m.attNames.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {m.attNames.map((name, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center gap-1 rounded bg-white/15 px-1.5 py-0.5 text-xs"
                        >
                          <FileText className="h-3 w-3" />
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
                {selectedUserId === m.id && (
                  <button
                    type="button"
                    onClick={() => copyUserMessage(m)}
                    className="absolute top-full right-0 mt-1.5 z-10 inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    {copiedId === m.id ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-green-600" />
                        已复制
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" />
                        复制
                      </>
                    )}
                  </button>
                )}
              </div>
            ) : (
              <div className="w-full">
                {m.content && (
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <Markdown>{m.content}</Markdown>
                  </div>
                )}

                {m.tools && m.tools.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {coalesceSearchTools(m.tools).map((t, i) => (
                      <ToolCard
                        key={i}
                        tool={t}
                        navigate={navigate}
                        archiveCandidates={assistantReplyCandidates(messages, m)}
                        archiveResult={t.archiveResult}
                        archiveError={t.archiveError}
                        onArchiveResult={(result, detail) =>
                          updateToolState(m.id, t, { archiveResult: result, archiveError: detail })
                        }
                        onDismiss={() => updateToolState(m.id, t, { dismissed: true })}
                      />
                    ))}
                  </div>
                )}

                {streaming && m.content === "" && (!m.tools || m.tools.length === 0) && !m.error && (
                  <div className="flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    思考中...
                  </div>
                )}

                {m.error && (
                  <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {m.error}
                  </div>
                )}
              </div>
            )}
          </div>
            ))}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="mx-auto w-full max-w-5xl shrink-0 border-t border-gray-200 px-4 pb-4 pt-3 dark:border-gray-700">
        <AttachmentList manager={attachments} compact />
        <div className="flex items-end gap-2">
          <div
            className="relative flex-1"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const files = e.dataTransfer.files;
              if (files.length > 0) attachments.addFiles(files);
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={2}
              placeholder="输入学习目标，可直接粘贴/拖入图片或文件…"
              className="w-full resize-none rounded-md border border-gray-300 bg-white py-3 pl-11 pr-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              onPaste={(e) => {
                const files = e.clipboardData?.files ?? [];
                if (files.length > 0) {
                  e.preventDefault();
                  attachments.addFiles(files);
                }
              }}
            />
            <button
              onClick={() => coachFileRef.current?.click()}
              disabled={streaming}
              title="附上学习资料（图片 / PDF / Word / 文本）"
              className="absolute bottom-3 left-3 inline-flex items-center justify-center rounded p-1 text-gray-400 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:text-indigo-400"
            >
              <Paperclip className="h-4 w-4" />
            </button>
          </div>
          <input
            ref={coachFileRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.txt,.md"
            multiple
            className="hidden"
            onChange={(e) => {
              attachments.addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={(!input.trim() && attachments.readyIds.length === 0) || streaming || attachments.hasActive}
            title={attachments.hasActive ? "附件解析中，稍候再发送" : undefined}
            className="inline-flex h-[42px] items-center gap-1.5 rounded-md bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}
