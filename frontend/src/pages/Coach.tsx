import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Send, Loader2, CheckCircle2, AlertCircle, ArrowRight, ClipboardList } from "lucide-react";
import { Markdown } from "../components/Markdown";
import { api } from "../api/client";

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

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolActivity[];
  error?: string;
  planCreated?: { planId: string; title: string };
}

const EXAMPLES = [
  "帮我制定 Python 装饰器的学习计划",
  "讲解一下闭包的概念，并出几道练习题",
  "把刚才的学习笔记保存到 IMA 知识库",
];

const STORAGE_KEY = "zhixue_coach_messages";

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
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

    const assistantId = uid();
    setInput("");
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: goal, tools: [] },
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
        (planId, title) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, planCreated: { planId, title } } : m,
            ),
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

        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
            <div
              className={
                m.role === "user"
                  ? "max-w-[80%] rounded-lg bg-indigo-600 px-4 py-2.5 text-sm text-white"
                  : "w-full"
              }
            >
              {m.role === "user" ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <>
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

                  {/* Plan created - navigation button */}
                  {m.planCreated && (
                    <button
                      onClick={() => navigate(`/plans/${m.planCreated!.planId}`)}
                      className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100 dark:border-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300 dark:hover:bg-indigo-900/50"
                    >
                      <ClipboardList className="h-4 w-4" />
                      查看计划：{m.planCreated.title}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  )}
                </>
              )}
            </div>
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
