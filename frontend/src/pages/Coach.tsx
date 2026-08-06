import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Send, Loader2, CheckCircle2, AlertCircle, ArrowRight, ClipboardList, Trash2, Search } from "lucide-react";
import { Markdown } from "../components/Markdown";
import { api } from "../api/client";
import type { PlanListItem } from "../api/types";

const TOOL_LABELS: Record<string, string> = {
  planner: "制定计划",
  content_author: "生成内容",
  quizzer: "设计测验",
  grader: "批改测验",
  task: "委派任务",
  read_file: "读取文件",
  write_file: "写入文件",
  edit_file: "编辑文件",
  ls: "浏览目录",
  glob: "搜索文件",
  grep: "搜索内容",
  execute: "执行命令",
  write_todos: "更新待办",
};

interface ToolActivity {
  name: string;
  label: string;
  status: "running" | "done";
}

type PlanIntentType = "create" | "search";

interface PlanIntent {
  type: PlanIntentType;
  topic: string;
  results?: PlanListItem[];
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolActivity[];
  error?: string;
  planIntent?: PlanIntent;
}

const EXAMPLES = [
  "帮我制定 Python 装饰器的学习计划",
  "有没有机器学习的学习计划",
  "讲解一下闭包的概念，并出几道练习题",
];

const STORAGE_KEY = "zhixue_coach_messages";

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// 当用户消息明确表达「制定 / 搜索学习计划」意图时，提取学习主题与意图类型。
// 搜索意图提取不到主题时返回空主题（展示全部计划）；创建意图提取不到主题时返回 null。
const SEARCH_SIGNALS = /(有没有|找一?下?|搜索|查看|看看|查一下|之前|现有|已有|做过|哪些)/;
const CREATE_SIGNALS = /(制定|规划|设计|整理|列)/;

function detectPlanIntent(text: string): PlanIntent | null {
  const t = text.trim();
  if (!t) return null;

  const hasPlanWord = /(学习计划|学习路径|学习路线|学习方案|学习规划|计划|路径|路线|方案)/.test(t);
  if (!hasPlanWord) return null;

  const hasSearch = SEARCH_SIGNALS.test(t);
  const hasCreate = CREATE_SIGNALS.test(t);
  const hasLearning = /学习/.test(t);
  if (!hasSearch && !hasCreate && !hasLearning) return null;

  const type: PlanIntentType = hasSearch ? "search" : "create";

  const patterns = [
    /(?:有没有|找一?下?|搜索|查看|看看|查一下)\s*(.+?)\s*(?:的)?(?:学习)?(?:计划|路径|路线|方案)/,
    /制定\s*(.+?)\s*(?:的)?学习计划/,
    /规划\s*(.+?)\s*(?:的)?(?:学习)?(?:路径|路线|规划)/,
    /(?:设计|整理)\s*(.+?)\s*(?:的)?学习(?:计划|方案)/,
    /(.+?)\s*(?:的)?学习计划/,
    /(.+?)\s*(?:的)?学习路径/,
    /(.+?)\s*(?:的)?学习路线/,
    /(.+?)\s*(?:的)?学习方案/,
    /学习\s*(.+?)\s*(?:的)?(?:计划|路径|路线|方案)/,
    /制定\s*(.+?)\s*(?:的)?计划/,
    /(?:有没有|找一?下?|搜索|查看|看看|查一下)\s*(.+?)\s*(?:的)?计划/,
    /规划\s*(.+?)\s*(?:的)?(?:路径|路线)/,
  ];
  let topic = "";
  for (const re of patterns) {
    const m = t.match(re);
    if (m && m[1] && m[1].trim()) {
      topic = m[1].trim();
      break;
    }
  }

  // 泛化问句（哪些/什么/几个…）无具体主题 -> 搜索时展示全部
  if (topic && /哪些|什么|几个|所有|全部/.test(topic)) topic = "";

  if (topic) {
    const lead = /^(帮我|请|我想|想要|麻烦|能不能|可以|一下|一个|一份|来|出|制定|规划|设计|整理|列个|列出|有没有|找一?下?|搜索|查看|看看|查一下|之前|现有|已有|做过)/;
    for (let i = 0; i < 3 && lead.test(topic); i++) topic = topic.replace(lead, "").trim();
    topic = topic
      .replace(/^个(?![人别位体例案性数])/, "")
      .replace(/^份(?![额量内])/, "")
      .replace(/^项(?!目)/, "")
      .replace(/^本(?![身质地能文])/, "")
      .replace(/^篇(?![章幅])/, "")
      .replace(/^道(?![路理德具])/, "")
      .replace(/^条(?![件理约])/, "")
      .replace(/^门(?![类户面槛派])/, "")
      .replace(/(一下|一个|一份|些|点|的|了|啊|吧|呢|[，。、！？!?,.\s])+$/, "")
      .replace(/^[，。、！？!?,.\s]+/, "")
      .trim();
    if (/^(个|份|项|道|篇|本|条|门|些|点|学习|计划|课程|知识)$/.test(topic)) topic = "";
  }

  if (!topic) return type === "search" ? { type: "search", topic: "" } : null;
  return { type, topic };
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

  const handleSend = async (text?: string) => {
    const goal = (text ?? input).trim();
    if (!goal || streaming) return;

    const userId = uid();
    const assistantId = uid();
    const intent = detectPlanIntent(goal);
    setInput("");
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: goal, tools: [], ...(intent ? { planIntent: intent } : {}) },
      { id: assistantId, role: "assistant", content: "", tools: [] },
    ]);

    // 搜索意图：按主题拉取已有计划（后端按标题过滤），挂到该用户消息上。
    if (intent?.type === "search") {
      api.listPlans(intent.topic || undefined)
        .then((results) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === userId && m.planIntent
                ? { ...m, planIntent: { ...m.planIntent, results } }
                : m,
            ),
          );
        })
        .catch(() => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === userId && m.planIntent
                ? { ...m, planIntent: { ...m.planIntent, results: [] } }
                : m,
            ),
          );
        });
    }

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
        (event, name) => {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m;
              const tools = [...m.tools];
              if (event === "on_tool_start") {
                tools.push({ name, label: TOOL_LABELS[name] || name, status: "running" });
              } else if (event === "on_tool_end") {
                const t = tools.find((t) => t.name === name && t.status === "running");
                if (t) t.status = "done";
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
              输入学习目标，AI 教练将自主规划并执行
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

        {messages.map((m) => {
          const intent = m.planIntent;
          return (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
              {m.role === "user" ? (
                <div className="flex max-w-[80%] flex-col items-end gap-2">
                  <div className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm text-white">
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  </div>
                  {intent?.type === "create" && (
                    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 dark:border-indigo-800 dark:bg-indigo-900/30">
                      <ClipboardList className="h-4 w-4 shrink-0 text-indigo-500 dark:text-indigo-400" />
                      <span className="text-sm text-indigo-700 dark:text-indigo-300">想要制定「{intent.topic}」的学习计划？</span>
                      <button
                        onClick={() => navigate(`/plans/new?topic=${encodeURIComponent(intent.topic)}`)}
                        className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                      >
                        制定计划
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                  {intent?.type === "search" && !intent.results && (
                    <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在搜索学习计划...
                    </div>
                  )}
                  {intent?.type === "search" && intent.results?.length === 0 && (
                    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 dark:border-indigo-800 dark:bg-indigo-900/30">
                      <Search className="h-4 w-4 shrink-0 text-indigo-500 dark:text-indigo-400" />
                      <span className="text-sm text-indigo-700 dark:text-indigo-300">
                        {intent.topic ? `没有找到「${intent.topic}」相关的学习计划` : "还没有学习计划"}
                      </span>
                      <button
                        onClick={() => navigate(intent.topic ? `/plans/new?topic=${encodeURIComponent(intent.topic)}` : "/plans/new")}
                        className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
                      >
                        制定计划
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                  {intent?.type === "search" && intent.results && intent.results.length > 0 && (
                    <div className="w-72 max-w-full rounded-lg border border-gray-200 bg-gray-50 p-2 dark:border-gray-700 dark:bg-gray-800">
                      <div className="flex items-center gap-1.5 px-1 pb-1.5 text-xs text-gray-500 dark:text-gray-400">
                        <Search className="h-3.5 w-3.5" />
                        {intent.topic ? `找到 ${intent.results.length} 个相关计划` : "你的学习计划"}
                      </div>
                      <div className="space-y-1">
                        {intent.results.map((p) => (
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
                  )}
                </div>
              ) : (
                <div className="w-full">
                  {/* Tool badges */}
                  {m.tools.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {m.tools.map((t, i) => (
                        <span
                          key={i}
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                            t.status === "running"
                              ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400"
                              : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
                          }`}
                        >
                          {t.status === "running" ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-3 w-3" />
                          )}
                          {t.label}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Content */}
                  {m.content && (
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <Markdown>{m.content}</Markdown>
                    </div>
                  )}

                  {/* Streaming indicator */}
                  {streaming && m.content === "" && m.tools.length === 0 && !m.error && (
                    <div className="flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      思考中...
                    </div>
                  )}

                  {/* Error */}
                  {m.error && (
                    <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {m.error}
                    </div>
                  )}
                </div>
              )}
          </div>
          );
        })}
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
