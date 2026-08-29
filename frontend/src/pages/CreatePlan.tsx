import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useCreatePlan } from "../hooks/usePlans";

export function CreatePlan() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const createPlan = useCreatePlan();
  const [mode, setMode] = useState<"topic" | "materials">("topic");
  const [input, setInput] = useState(() => searchParams.get("topic") ?? "");

  const handleSubmit = () => {
    if (!input.trim()) return;
    createPlan.mutate(
      { input, mode },
      {
        onSuccess: (doc) => {
          navigate(`/plans/${doc.id}`);
        },
      },
    );
  };

  return (
    <div className="mx-auto w-full max-w-2xl">
      <button
        onClick={() => navigate("/")}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <h1 className="mb-6 text-lg font-semibold text-gray-900 dark:text-gray-100">新建学习计划</h1>

      <div className="mb-4">
        <div className="inline-flex rounded-md border border-gray-200 p-0.5 dark:border-gray-700">
          {([
            { key: "topic", label: "主题" },
            { key: "materials", label: "学习资料" },
          ] as const).map((opt) => (
            <button
              key={opt.key}
              onClick={() => setMode(opt.key)}
              className={`rounded px-4 py-1.5 text-sm font-medium transition ${
                mode === opt.key
                  ? "bg-indigo-600 text-white dark:bg-indigo-500"
                  : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        rows={8}
        placeholder={mode === "topic"
          ? "输入要学习的主题，如「Python 装饰器基础」"
          : "粘贴学习资料文本，系统将基于资料生成计划"}
        className="mb-4 w-full rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      />

      {createPlan.isError && (
        <p className="mb-4 text-sm text-red-600 dark:text-red-400">
          生成失败：{(createPlan.error as Error).message}
        </p>
      )}

      <button
        onClick={handleSubmit}
        disabled={!input.trim() || createPlan.isPending}
        className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
      >
        {createPlan.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
        {createPlan.isPending ? "生成中..." : "生成计划"}
      </button>
    </div>
  );
}
