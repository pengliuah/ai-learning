import { useState, useRef, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Send, Loader2, AlertCircle, ArrowRight, ClipboardList, Search, Trash2 } from "lucide-react";
import { Markdown } from "../components/Markdown";
import { api } from "../api/client";
import type { PlanListItem } from "../api/types";

const TOOL_LABELS: Record<string, string> = {
  create_plan: "制定计划",
  search_plans: "搜索计划",
};

interface ToolEvent {
  name: string;
  phase: "start" | "end";
  data?: { topic?: string } | PlanListItem[];
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

const STORAGE_KEY = "zhixue_coach_messages";

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
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
          没有找到相关的学习计划
        </div>
      );
    }
    return (
      <div className="w-72 max-w-full rounded-lg border border-gray-200 bg-gray-50 p-2 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-1.5 px-1 pb-1.5 text-xs text-gray-500 dark:text-gray-400">
          <Search className="h-3.5 w-3.5" />
          找到 {results.length} 个计划
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
  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {}
  }, [messages]);

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

  const handleSend = async (text?: string) => {
    const goal = (text ?? input).trim();
    if (!goal || streaming) return;

    const assistantId = uid();
    setInput("");
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: goal },
      { id: assistantId, role: "assistant", content: "", tools: [] },
    ]);

    try {
      await api.streamCoach(
        goal,
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
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      {/* Header */}
      <div className="mb-3 flex items-center gap-3">
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

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4">
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

        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
            {m.role === "user" ? (
              <div className="max-w-[80%] rounded-lg bg-indigo-600 px-4 py-2.5 text-sm text-white">
                <p className="whitespace-pre-wrap">{m.content}</p>
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
                    {m.tools.map((t, i) => (
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

      {/* Input */}
      <div className="border-t border-gray-200 pt-3 dark:border-gray-700">
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
