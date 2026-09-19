import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, RotateCcw, X } from "lucide-react";
import { api } from "../api/client";
import type { Attachment } from "../api/types";

/**
 * 学习资料附件：上传 → 后端自动转写 → 轮询状态，一条龙封装。
 * useAttachmentManager 管状态与请求，AttachmentList 只管渲染。
 * CreatePlan（页签上传区）与 Coach（输入框 📎）共用。
 */

export type AttachmentItem = {
  att: Attachment;
  /** 上传还没拿到服务端 id 时的本地临时标记 */
  localId: string;
  progress?: number; // 上传进度 0-100（上传中才有）
  file?: File; // 保留原始文件：上传失败重试要用
};

const POLL_INTERVAL_MS = 2000;

export function useAttachmentManager() {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const seq = useRef(0);

  const patch = useCallback((localId: string, p: Partial<AttachmentItem>) => {
    setItems((prev) => prev.map((it) => (it.localId === localId ? { ...it, ...p } : it)));
  }, []);

  const uploadOne = useCallback(
    async (file: File, localId: string) => {
      patch(localId, { progress: 0 });
      try {
        const att = await api.uploadFile(file, (pct) => patch(localId, { progress: pct }));
        patch(localId, { att, file: undefined });
      } catch (err) {
        patch(localId, {
          file,
          att: {
            id: "", filename: file.name, mime: file.type || "application/octet-stream",
            sizeBytes: file.size, transcriptStatus: "failed",
            transcript: err instanceof Error ? err.message : "上传失败",
          },
        });
      }
    },
    [patch],
  );

  const addFiles = useCallback(
    (files: FileList | File[] | null) => {
      if (!files) return;
      for (const file of Array.from(files)) {
        const localId = `local-${Date.now()}-${seq.current++}`;
        setItems((prev) => [
          ...prev,
          {
            localId,
            file,
            att: {
              id: "", filename: file.name, mime: file.type || "application/octet-stream",
              sizeBytes: file.size, transcriptStatus: "pending", transcript: "",
            },
          },
        ]);
        void uploadOne(file, localId);
      }
    },
    [uploadOne],
  );

  const remove = useCallback((item: AttachmentItem) => {
    // 已拿到服务端 id 的同时删服务端行（尽力而为, 失败不阻塞 UI）
    if (item.att.id) void api.deleteFile(item.att.id).catch(() => {});
    setItems((prev) => prev.filter((it) => it.localId !== item.localId));
  }, []);

  /** 随消息发出后从输入区清掉，但保留服务端附件（转写已被引用）。 */
  const detach = useCallback((ids: string[]) => {
    if (ids.length === 0) return;
    const idSet = new Set(ids);
    setItems((prev) => prev.filter((it) => !it.att.id || !idSet.has(it.att.id)));
  }, []);

  const retry = useCallback(
    (item: AttachmentItem) => {
      if (item.file) {
        // 上传本身就失败了: 带着原文件重来
        setItems((prev) => prev.filter((it) => it.localId !== item.localId));
        void uploadOne(item.file, item.localId);
      } else if (item.att.id) {
        // 转写失败: 调后端重试端点, 状态回到 pending 等轮询
        patch(item.localId, {
          att: { ...item.att, transcriptStatus: "pending", transcript: "" },
        });
        void api.retryTranscribe(item.att.id).catch(() => {});
      }
    },
    [patch, uploadOne],
  );

  // 轮询: 有 pending/running 的附件时每 2s 刷新一次状态
  const needsPoll = items.some(
    (it) => it.att.id && (it.att.transcriptStatus === "pending" || it.att.transcriptStatus === "running"),
  );
  useEffect(() => {
    if (!needsPoll) return;
    const timer = setInterval(async () => {
      const pending = items.filter(
        (it) => it.att.id && (it.att.transcriptStatus === "pending" || it.att.transcriptStatus === "running"),
      );
      await Promise.all(pending.map(async (it) => {
        try {
          const fresh = await api.getFile(it.att.id);
          setItems((prev) =>
            prev.map((x) => (x.localId === it.localId ? { ...x, att: fresh } : x)),
          );
        } catch {
          // 单次轮询失败忽略, 下一轮再试
        }
      }));
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [needsPoll, items]);

  const readyIds = items
    .filter((it) => it.att.id && it.att.transcriptStatus === "done")
    .map((it) => it.att.id);
  const hasActive = items.some(
    (it) =>
      !it.att.id || // 还在上传
      it.att.transcriptStatus === "pending" ||
      it.att.transcriptStatus === "running",
  );
  const hasFailed = items.some((it) => it.att.transcriptStatus === "failed");

  return { items, addFiles, remove, retry, detach, readyIds, hasActive, hasFailed };
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

function StatusBadge({ item, onRetry }: { item: AttachmentItem; onRetry: () => void }) {
  const { att, progress } = item;
  if (!att.id && att.transcriptStatus === "pending") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        上传中 {progress !== undefined ? `${progress}%` : ""}
      </span>
    );
  }
  switch (att.transcriptStatus) {
    case "pending":
    case "running":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
          <Loader2 className="h-3 w-3 animate-spin" />
          解析中…
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-xs text-red-600 dark:text-red-400">
          {att.transcript || "处理失败"}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRetry();
            }}
            className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 hover:bg-red-50 dark:hover:bg-red-950"
            title="重试"
          >
            <RotateCcw className="h-3 w-3" />
            重试
          </button>
        </span>
      );
    default:
      return <span className="text-xs text-emerald-600 dark:text-emerald-400">已就绪</span>;
  }
}

export function AttachmentList({
  manager,
  compact = false,
}: {
  manager: ReturnType<typeof useAttachmentManager>;
  compact?: boolean; // chat 变体: 行更紧凑, 跟在输入框上方
}) {
  const { items, remove, retry } = manager;
  if (items.length === 0) return null;
  return (
    <div className={compact ? "mb-2 space-y-1.5" : "mb-4 space-y-2"}>
      {items.map((item) => (
        <div
          key={item.localId}
          className={`flex items-center gap-3 rounded-md border border-gray-200 bg-white px-3 dark:border-gray-700 dark:bg-gray-800 ${
            compact ? "py-1.5" : "py-2"
          }`}
        >
          <FileText className="h-4 w-4 shrink-0 text-gray-400" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-gray-900 dark:text-gray-100">{item.att.filename}</div>
            <div className="text-xs text-gray-400">{formatSize(item.att.sizeBytes)}</div>
          </div>
          <StatusBadge item={item} onRetry={() => retry(item)} />
          <button
            onClick={() => remove(item)}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300"
            title="移除"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
