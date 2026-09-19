import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, FileText, Film, FileAudio, FileImage, Loader2,
  Play, RotateCcw, Trash2, Upload,
} from "lucide-react";
import { api } from "../api/client";
import type { Attachment } from "../api/types";
import { AttachmentPreviewModal, isImageMime } from "../components/Attachments";
import { useToast } from "../components/Toast";

/**
 * 「学习资料」附件管理页：列出当前用户上传的全部文件，
 * 可预览（图片/PDF 原文件、文本文档看转写结果）、下载、删除、手动解析。
 * 上传只存盘不转写；解析在点「解析」或计划/教练页提交时发生。
 */

const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.txt,.md";

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fileIcon(mime: string) {
  if (isImageMime(mime)) return FileImage;
  if (mime.startsWith("video/")) return Film;
  if (mime.startsWith("audio/")) return FileAudio;
  return FileText;
}

function StatusBadge({ att }: { att: Attachment }) {
  switch (att.transcriptStatus) {
    case "pending":
      return (
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500 dark:bg-gray-900 dark:text-gray-400">
          待解析
        </span>
      );
    case "running":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-300">
          <Loader2 className="h-3 w-3 animate-spin" />
          解析中
        </span>
      );
    case "failed":
      return (
        <span
          className="inline-flex max-w-48 items-center gap-1 truncate rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300"
          title={att.transcript || "解析失败"}
        >
          失败{att.transcript ? `：${att.transcript}` : ""}
        </span>
      );
    default:
      return (
        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
          已就绪
        </span>
      );
  }
}

export function Files() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [items, setItems] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listFiles();
      setItems(list);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 有解析中的附件时轮询刷新
  const needsPoll = items.some(
    (a) => a.transcriptStatus === "pending" || a.transcriptStatus === "running",
  );
  useEffect(() => {
    if (!needsPoll) return;
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [needsPoll, refresh]);

  const handleUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      const results: Attachment[] = [];
      for (const f of Array.from(files)) {
        results.push(await api.uploadFile(f));
      }
      const reusedCount = results.filter((r) => r.reused).length;
      if (reusedCount === results.length && results.length > 0) {
        toast("文件之前上传过，已直接复用", "success");
      } else if (reusedCount > 0) {
        toast(`上传成功（${reusedCount} 个文件复用了已有记录）`, "success");
      } else {
        toast("上传成功", "success");
      }
      await refresh();
    } catch (e) {
      toast(`上传失败：${(e as Error).message}`, "error");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (att: Attachment) => {
    try {
      await api.deleteFile(att.id);
      setItems((prev) => prev.filter((a) => a.id !== att.id));
      setConfirmDeleteId(null);
      toast("已删除", "success");
    } catch (e) {
      toast(`删除失败：${(e as Error).message}`, "error");
    }
  };

  /** 手动发起解析（pending / failed 都可用），状态交给轮询刷新 */
  const handleTranscribe = async (att: Attachment) => {
    try {
      await api.retryTranscribe(att.id);
      setItems((prev) =>
        prev.map((a) => (a.id === att.id ? { ...a, transcriptStatus: "running", transcript: "" } : a)),
      );
    } catch (e) {
      toast(`发起解析失败：${(e as Error).message}`, "error");
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">学习资料</h1>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            你上传过的全部附件。生成计划或教练对话引用时会用多模态模型把文件解析成文字；这里可预览原件、手动解析、下载和删除。
          </p>
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          上传文件
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => {
            void handleUpload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">加载失败：{error}</p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 py-16 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500 dark:text-gray-400">还没有上传过文件</p>
          <p className="mt-1 text-xs text-gray-400">
            在「新建计划 → 学习资料」或 AI 教练输入框 📎 处上传，图片 / PDF / Word / 文本都可以
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((att) => {
            const Icon = fileIcon(att.mime);
            const canParse = att.transcriptStatus === "pending" || att.transcriptStatus === "failed";
            return (
              <div
                key={att.id}
                className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-gray-50 dark:bg-gray-900">
                  <Icon className="h-5 w-5 text-gray-400" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{att.filename}</p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                    <span>{formatSize(att.sizeBytes)}</span>
                    <span>{formatDate(att.createdAt)}</span>
                    <StatusBadge att={att} />
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  {canParse && (
                    <button
                      onClick={() => void handleTranscribe(att)}
                      className="rounded p-2 text-gray-400 hover:bg-gray-100 hover:text-emerald-600 dark:hover:bg-gray-700 dark:hover:text-emerald-400"
                      title={att.transcriptStatus === "pending" ? "开始解析" : "重试解析"}
                    >
                      {att.transcriptStatus === "pending" ? <Play className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}
                    </button>
                  )}
                  <button
                    onClick={() => setPreview(att)}
                    className="rounded p-2 text-gray-400 hover:bg-gray-100 hover:text-indigo-600 dark:hover:bg-gray-700 dark:hover:text-indigo-400"
                    title="预览"
                  >
                    预览
                  </button>
                  {confirmDeleteId === att.id ? (
                    <button
                      onClick={() => void handleDelete(att)}
                      onBlur={() => setConfirmDeleteId(null)}
                      className="ml-1 rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700"
                      autoFocus
                    >
                      确认删除
                    </button>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(att.id)}
                      className="rounded p-2 text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-700 dark:hover:text-red-400"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {preview && <AttachmentPreviewModal att={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}
