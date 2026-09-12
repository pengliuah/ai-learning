import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, Send, Loader2, AlertCircle, ArrowRight, ClipboardList,
  Search, Trash2, Copy, Check,
} from "lucide-react";
import { Markdown } from "../components/Markdown";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ChatTurn, PlanListItem } from "../api/types";

const TOOL_LABELS: Record<string, string> = {
  create_plan: "制定计划",
  search_plans: "搜索计划",
};

interface ToolEvent {
  name: string;
  phase: "start" | "end";
  data?: { topic?: string } | PlanListItem[];
  note?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: string;
  tools?: ToolEvent[];
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

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/** 同一条回复里模型可能换关键词连续调用 search_plans，每次都渲染一张卡会堆满屏幕。
 *  收敛成一张：保留最后一次的结果，被合并的次数放进提示文案。 */
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

function ToolCard({ tool, navigate }: { tool: ToolEvent; navigate: ReturnType<typeof useNavigate> }) {
  const label = TOOL_LABELS[tool.name] || tool.name;
  if (tool.phase === "start") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在{label}...
      </div>
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

  const handleSend = async (text?: string) => {
    const goal = (text ?? input).trim();
    if (!goal || streaming) return;

    const assistantId = uid();
    setInput("");
    setSelectedUserId(null);
    setStreaming(true);
    stickToBottom.current = true;
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: goal },
      { id: assistantId, role: "assistant", content: "", tools: [] },
    ]);

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
      <div className="mb-3 flex shrink-0 items-center gap-3 px-4 pt-4">
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
            if (confirm("清除所有聊天历史？")) setMessages([]);
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
          <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-2">
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
                      <ToolCard key={i} tool={t} navigate={navigate} />
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
      <div className="shrink-0 border-t border-gray-200 px-4 pb-4 pt-3 dark:border-gray-700">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={2}
            placeholder="输入学习目标..."
            className="flex-1 resize-none rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || streaming}
            className="inline-flex h-[42px] items-center gap-1.5 rounded-md bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}
