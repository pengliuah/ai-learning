import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, RotateCcw, X } from "lucide-react";
import { api } from "../api/client";
import type { Attachment } from "../api/types";

/**
 * 学习资料附件：上传（只存盘，不自动转写）→ 缩略图预览原件 →
 * 用户点「生成计划」/「发送」时才由 ensureTranscribed 触发多模态转写。
 * useAttachmentManager 管状态与请求，AttachmentList 只管渲染。
 * CreatePlan（页签上传区）与 Coach（输入框 📎）共用。
 */

export type AttachmentItem = {
  att: Attachment;
  /** 上传还没拿到服务端 id 时的本地临时标记 */
  localId: string;
  progress?: number; // 上传进度 0-100（上传中才有）
  file?: File; // 保留原始文件: 上传中做缩略图, 失败重传要用
};

const POLL_INTERVAL_MS = 2000;

/** 待解析徽标等共用的小工具 */
export function isImageMime(mime: string): boolean {
  return mime.startsWith("image/");
}

/** 可预览原始文件的类型（其余类型预览转写文本） */
export function previewableRaw(mime: string): boolean {
  return mime.startsWith("image/") || mime === "application/pdf";
}

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
        // 只存盘不转写: 保持 pending, 等 ensureTranscribed 触发
        patch(localId, { att, progress: undefined });
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
      if (item.file && !item.att.id) {
        // 上传本身就失败了: 带着原文件重来
        setItems((prev) => prev.filter((it) => it.localId !== item.localId));
        void uploadOne(item.file, item.localId);
      } else if (item.att.id) {
        // 转写失败/待解析: 调后端转写端点, 状态回到 running 等轮询
        patch(item.localId, {
          att: { ...item.att, transcriptStatus: "running", transcript: "" },
        });
        void api.retryTranscribe(item.att.id).catch(() => {});
      }
    },
    [patch, uploadOne],
  );

  /**
   * 提交前统一转写: 把所有未完成的附件（pending / failed / running）发起
   * 解析并等结果。全部成功返回就绪的附件 id 列表；任一失败抛错（各项的
   * 失败原因已写回条目状态, UI 可见）。
   */
  const ensureTranscribed = useCallback(async (): Promise<string[]> => {
    const targets = items.filter((it) => it.att.id && it.att.transcriptStatus !== "done");
    const doneIds = items
      .filter((it) => it.att.id && it.att.transcriptStatus === "done")
      .map((it) => it.att.id);
    if (targets.length === 0) return doneIds;

    for (const it of targets) {
      patch(it.localId, { att: { ...it.att, transcriptStatus: "running", transcript: "" } });
    }
    // 发起失败不吞: 标记条目失败并中止提交 (此前吞掉导致无限轮询 pending)
    try {
      await Promise.all(targets.map((it) => api.retryTranscribe(it.att.id)));
    } catch (err) {
      const msg = (err as Error).message || "网络错误";
      setItems((prev) =>
        prev.map((x) =>
          targets.some((t) => t.localId === x.localId)
            ? { ...x, att: { ...x.att, transcriptStatus: "failed", transcript: msg } }
            : x,
        ),
      );
      throw new Error(`附件解析发起失败：${msg}`);
    }

    // 轮询直到所有目标落到 done / failed
    let latest = new Map<string, Attachment>();
    for (let round = 0; round < 300; round++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      const fresh = await Promise.all(
        targets.map(async (it) => ({
          localId: it.localId,
          att: await api.getFile(it.att.id).catch(() => null),
        })),
      );
      latest = new Map(fresh.filter((f) => f.att).map((f) => [f.localId, f.att!]));
      setItems((prev) =>
        prev.map((x) => (latest.has(x.localId) ? { ...x, att: latest.get(x.localId)! } : x)),
      );
      const settled = [...latest.values()].every(
        (a) => a.transcriptStatus === "done" || a.transcriptStatus === "failed",
      );
      if (settled) break;
    }
    const failed = [...latest.values()].filter((a) => a.transcriptStatus === "failed");
    if (failed.length > 0) {
      throw new Error(`附件「${failed[0].filename}」解析失败：${failed[0].transcript || "未知原因"}`);
    }
    return [...latest.values()]
      .filter((a) => a.transcriptStatus === "done")
      .map((a) => a.id);
  }, [items, patch]);

  const readyIds = items
    .filter((it) => it.att.id && it.att.transcriptStatus === "done")
    .map((it) => it.att.id);
  // 上传中或转写进行中 → 不可提交; 单纯"待解析"不阻塞（提交时会先转写）
  const hasActive = items.some(
    (it) => !it.att.id || it.att.transcriptStatus === "running",
  );
  const hasFailed = items.some((it) => it.att.transcriptStatus === "failed");
  const hasPending = items.some((it) => it.att.id && it.att.transcriptStatus === "pending");

  return {
    items, addFiles, remove, retry, detach, ensureTranscribed,
    readyIds, hasActive, hasFailed, hasPending,
  };
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

/** 缩略图: 图片显示真实缩略图（上传中用本地 File, 之后用服务端原件）,
 *  其他类型显示文件图标。 */
function Thumb({ item }: { item: AttachmentItem }) {
  const isImage = isImageMime(item.att.mime);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!isImage) return;
    let revoked: string | null = null;
    let cancelled = false;
    const set = (u: string) => {
      if (cancelled) {
        URL.revokeObjectURL(u);
        return;
      }
      revoked = u;
      setUrl(u);
    };
    if (item.file) {
      set(URL.createObjectURL(item.file));
    } else if (item.att.id) {
      void api.fileRawUrl(item.att.id).then(set).catch(() => {});
    }
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [isImage, item.file, item.att.id]);

  if (!isImage) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900">
        <FileText className="h-5 w-5 text-gray-400" />
      </div>
    );
  }
  return (
    <div className="h-10 w-10 shrink-0 overflow-hidden rounded border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900">
      {url ? (
        <img src={url} alt={item.att.filename} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />
        </div>
      )}
    </div>
  );
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
      return <span className="text-xs text-gray-400">待解析</span>;
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

/** 预览弹窗：图片/PDF 显示原始文件，文本文档显示转写结果，均带下载按钮。
 *  管理页 (Files.tsx) 与上传列表共用。 */
export function AttachmentPreviewModal({
  att,
  onClose,
}: {
  att: Attachment;
  onClose: () => void;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!previewableRaw(att.mime)) return;
    let revoked: string | null = null;
    let cancelled = false;
    api
      .fileRawUrl(att.id)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        revoked = url;
        setBlobUrl(url);
      })
      .catch((e) => setError((e as Error).message));
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [att]);

  const download = async () => {
    const url = blobUrl ?? (await api.fileRawUrl(att.id).catch(() => null));
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = att.filename;
    a.click();
    if (url !== blobUrl) URL.revokeObjectURL(url);
  };

  const showTranscript = att.transcript && !previewableRaw(att.mime);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-800"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <FileText className="h-4 w-4 shrink-0 text-gray-400" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{att.filename}</p>
            <p className="text-xs text-gray-400">
              {formatSize(att.sizeBytes)}
              {att.createdAt ? ` · ${new Date(att.createdAt).toLocaleString("zh-CN")}` : ""}
            </p>
          </div>
          <button
            onClick={download}
            className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            title="下载原始文件"
          >
            下载
          </button>
          <button
            onClick={onClose}
            className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {error ? (
            <p className="text-sm text-red-600 dark:text-red-400">加载失败：{error}</p>
          ) : att.mime.startsWith("image/") ? (
            blobUrl ? (
              <img src={blobUrl} alt={att.filename} className="mx-auto max-h-[65vh] object-contain" />
            ) : (
              <div className="flex justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
              </div>
            )
          ) : att.mime === "application/pdf" ? (
            blobUrl ? (
              <iframe src={blobUrl} title={att.filename} className="h-[65vh] w-full rounded border border-gray-200 dark:border-gray-700" />
            ) : (
              <div className="flex justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
              </div>
            )
          ) : showTranscript ? (
            <pre className="whitespace-pre-wrap text-sm text-gray-800 dark:text-gray-200">{att.transcript}</pre>
          ) : (
            <p className="py-8 text-center text-sm text-gray-400">
              {att.transcriptStatus === "failed"
                ? `解析失败：${att.transcript || "未知原因"}`
                : att.transcriptStatus === "done"
                  ? "该文件没有可预览的内容"
                  : "该文件尚未解析；生成计划或发送消息后自动解析，也可在「学习资料」页手动解析"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function AttachmentList({
  manager,
  compact = false,
}: {
  manager: ReturnType<typeof useAttachmentManager>;
  compact?: boolean; // chat 变体: 行更紧凑, 跟在输入框上方
}) {
  const { items, remove, retry } = manager;
  const [previewItem, setPreviewItem] = useState<AttachmentItem | null>(null);
  if (items.length === 0) return null;
  return (
    <div className={compact ? "mb-2 space-y-1.5" : "mb-4 space-y-2"}>
      {items.map((item) => (
        <div
          key={item.localId}
          onClick={item.att.id ? () => setPreviewItem(item) : undefined}
          className={`flex items-center gap-3 rounded-md border border-gray-200 bg-white px-3 dark:border-gray-700 dark:bg-gray-800 ${
            compact ? "py-1.5" : "py-2"
          } ${item.att.id ? "cursor-pointer hover:border-indigo-300 dark:hover:border-indigo-600" : ""}`}
          title={item.att.id ? "点击查看原件" : undefined}
        >
          <Thumb item={item} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-gray-900 dark:text-gray-100">{item.att.filename}</div>
            <div className="text-xs text-gray-400">{formatSize(item.att.sizeBytes)}</div>
          </div>
          <StatusBadge item={item} onRetry={() => retry(item)} />
          <button
            onClick={(e) => {
              e.stopPropagation();
              remove(item);
            }}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300"
            title="移除"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      {previewItem && (
        <AttachmentPreviewModal att={previewItem.att} onClose={() => setPreviewItem(null)} />
      )}
    </div>
  );
}
