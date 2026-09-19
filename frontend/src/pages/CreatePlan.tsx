import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2, Upload } from "lucide-react";
import { useCreatePlan } from "../hooks/usePlans";
import { AttachmentList, useAttachmentManager } from "../components/Attachments";

const ACCEPT =
  ".png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.txt,.md";

export function CreatePlan() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const createPlan = useCreatePlan();
  const [mode, setMode] = useState<"topic" | "materials">("topic");
  const [input, setInput] = useState(() => searchParams.get("topic") ?? "");
  const [elapsed, setElapsed] = useState(0);
  const attachments = useAttachmentManager();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // 生成通常需要 1-3 分钟: 显示等待时长, 避免用户以为卡死而退出
  useEffect(() => {
    if (!createPlan.isPending) {
      setElapsed(0);
      return;
    }
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [createPlan.isPending]);

  // 学习资料模式下支持直接 Ctrl+V 粘贴截图/复制的文件
  useEffect(() => {
    if (mode !== "materials") return;
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.length > 0) {
        e.preventDefault();
        attachments.addFiles(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [mode, attachments]);

  const attachmentsReady =
    attachments.items.length > 0 && !attachments.hasActive;
  const canSubmit =
    mode === "topic"
      ? !!input.trim()
      : (attachments.readyIds.length > 0 || !!input.trim()) && !attachments.hasActive;

  const handleSubmit = useCallback(() => {
    if (!canSubmit || createPlan.isPending) return;
    createPlan.mutate(
      {
        input,
        mode,
        attachmentIds: mode === "materials" ? attachments.readyIds : [],
      },
      {
        onSuccess: (doc) => {
          navigate(`/plans/${doc.id}`);
        },
      },
    );
  }, [canSubmit, createPlan, input, mode, attachments.readyIds, navigate]);

  return (
    <div className="mx-auto w-full max-w-5xl">
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

      {mode === "materials" && (
        <>
          <AttachmentList manager={attachments} />
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              attachments.addFiles(e.dataTransfer.files);
            }}
            className={`mb-3 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition ${
              dragging
                ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-950/40"
                : "border-gray-300 hover:border-indigo-400 hover:bg-gray-50 dark:border-gray-600 dark:hover:border-indigo-500 dark:hover:bg-gray-800/60"
            }`}
          >
            <Upload className="h-6 w-6 text-gray-400" />
            <p className="text-sm text-gray-600 dark:text-gray-300">
              点击上传，或把文件拖到这里（截图可直接 Ctrl+V 粘贴）
            </p>
            <p className="text-xs text-gray-400">
              支持 图片 / PDF / Word / 文本，单个文件 ≤ 50MB，系统将用全模态模型解析内容
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                attachments.addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        </>
      )}

      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        rows={mode === "materials" ? 4 : 8}
        placeholder={mode === "topic"
          ? "输入要学习的主题，如「Python 装饰器基础」"
          : "（可选）补充说明：想基于这些资料学到什么程度、有什么侧重…"}
        className="mb-4 w-full rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      />

      {createPlan.isError && (
        <p className="mb-4 text-sm text-red-600 dark:text-red-400">
          生成失败：{(createPlan.error as Error).message}
        </p>
      )}

      {createPlan.isPending && elapsed > 20 && (
        <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
          已等待 {elapsed} 秒 —— 生成一份多模块计划通常需要 1-3 分钟，请保持页面打开。
        </p>
      )}

      {attachments.hasFailed && (
        <p className="mb-4 text-sm text-amber-600 dark:text-amber-400">
          有附件解析失败，生成计划时将跳过它（可重试或移除）。
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit || createPlan.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          {createPlan.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          {createPlan.isPending ? "生成中..." : "生成计划"}
        </button>
        {mode === "materials" && attachments.hasActive && (
          <span className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            文件解析完成后才能生成计划
          </span>
        )}
      </div>
    </div>
  );
}
