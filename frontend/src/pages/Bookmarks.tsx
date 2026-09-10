import { Link, useNavigate } from "react-router-dom";
import { useState, type ReactNode } from "react";
import {
  ArrowLeft, Bookmark, BookOpen, Brain, ChevronDown, Trash2,
} from "lucide-react";
import { useBookmarks, useDeleteBookmark } from "../hooks/usePlans";
import {
  useDeleteMemory,
  useMemories,
  useMemorySettings,
  useUpdateMemorySettings,
} from "../hooks/useSettings";
import { useToast } from "../components/Toast";
import type { BookmarkItem, MemoryItem } from "../api/types";

function formatMemoryDate(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function SectionHeader({
  open,
  onToggle,
  icon,
  title,
  desc,
  count,
  trailing,
}: {
  open: boolean;
  onToggle: () => void;
  icon: ReactNode;
  title: string;
  desc: string;
  count?: number;
  trailing?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="min-w-0 flex-1 text-left"
      >
        <h2 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-gray-100">
          <ChevronDown
            className={[
              "h-4 w-4 shrink-0 text-gray-400 transition-transform dark:text-gray-500",
              open ? "" : "-rotate-90",
            ].join(" ")}
          />
          {icon}
          {title}
          {typeof count === "number" && (
            <span className="ml-1 rounded-full bg-gray-100 px-1.5 py-0.5 text-xs font-normal text-gray-500 dark:bg-gray-700 dark:text-gray-400">
              {count}
            </span>
          )}
        </h2>
        <p className="mt-0.5 pl-5 text-xs text-gray-500 dark:text-gray-400">{desc}</p>
      </button>
      {trailing}
    </div>
  );
}

export function Bookmarks() {
  const navigate = useNavigate();
  const { data: bookmarks, isLoading: bookmarksLoading } = useBookmarks();
  const deleteBookmark = useDeleteBookmark();
  const { data: memories, isLoading: memoriesLoading } = useMemories();
  const { data: memorySettings, isLoading: settingsLoading } = useMemorySettings();
  const updateMemorySettings = useUpdateMemorySettings();
  const deleteMemory = useDeleteMemory();
  const { toast } = useToast();

  const [memoryOpen, setMemoryOpen] = useState(true);
  const [bookmarksOpen, setBookmarksOpen] = useState(true);

  const memoryEnabled = memorySettings?.enabled ?? true;

  const jump = (b: BookmarkItem) => {
    navigate(`/plans/${b.planId}/modules/${b.moduleId}?bookmark=${b.id}`);
  };

  const onToggleMemory = () => {
    const next = !memoryEnabled;
    updateMemorySettings.mutate(
      { enabled: next },
      {
        onSuccess: () =>
          toast(next ? "已开启长期记忆" : "已关闭长期记忆（不再写入/召回）", "success"),
        onError: (e) => toast(`切换失败：${(e as Error).message}`, "error"),
      },
    );
  };

  const onDeleteMemory = (m: MemoryItem) => {
    if (!confirm("确定删除这条记忆？删除后教练将不再记得该事实。")) return;
    deleteMemory.mutate(m.id, {
      onError: (e) => toast(`删除失败：${(e as Error).message}`, "error"),
    });
  };

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="mb-3 flex items-center gap-3">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回
        </Link>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">我的记录</h1>
      </div>

      {/* ---- 长期记忆 ---- */}
      <section className="mb-8">
        <SectionHeader
          open={memoryOpen}
          onToggle={() => setMemoryOpen((v) => !v)}
          icon={<Brain className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />}
          title="长期记忆"
          desc="AI 教练跨会话记住的学习偏好与约定。关闭后不再写入或召回。"
          count={memories?.length}
          trailing={
            <button
              type="button"
              role="switch"
              aria-checked={memoryEnabled}
              aria-label="长期记忆总开关"
              disabled={settingsLoading || updateMemorySettings.isPending}
              onClick={(e) => {
                e.stopPropagation();
                onToggleMemory();
              }}
              className={[
                "relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors",
                memoryEnabled ? "bg-indigo-600" : "bg-gray-300 dark:bg-gray-600",
                (settingsLoading || updateMemorySettings.isPending) && "opacity-60",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span
                className={[
                  "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
                  memoryEnabled && "translate-x-5",
                ]
                  .filter(Boolean)
                  .join(" ")}
              />
            </button>
          }
        />

        {memoryOpen && (
          <>
            {memoriesLoading && (
              <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>
            )}

            {!memoriesLoading && memories && memories.length === 0 && (
              <div className="rounded-lg border border-dashed border-gray-300 py-10 text-center dark:border-gray-600">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  还没有长期记忆。和 AI 教练聊过学习偏好后，值得记住的事实会出现在这里。
                </p>
              </div>
            )}

            {!memoriesLoading && memories && memories.length > 0 && (
              <div className="space-y-2">
                {memories.map((m) => (
                  <div
                    key={m.id}
                    className="group flex items-stretch overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
                  >
                    <div className="min-w-0 flex-1 px-4 py-3">
                      <p className="text-sm text-gray-900 dark:text-gray-100">{m.memory}</p>
                      {(m.createdAt || m.updatedAt) && (
                        <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
                          {formatMemoryDate(m.updatedAt || m.createdAt)}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => onDeleteMemory(m)}
                      aria-label="删除记忆"
                      className="flex w-10 shrink-0 items-center justify-center text-gray-300 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 dark:text-gray-600 dark:hover:bg-red-900/40 dark:hover:text-red-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {/* ---- 书签 ---- */}
      <section>
        <SectionHeader
          open={bookmarksOpen}
          onToggle={() => setBookmarksOpen((v) => !v)}
          icon={<Bookmark className="h-4 w-4 text-amber-500" />}
          title="我的书签"
          desc="学习内容里收藏的原文位置，点击可跳转回去。"
          count={bookmarks?.length}
        />

        {bookmarksOpen && (
          <>
            {bookmarksLoading && (
              <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>
            )}

            {bookmarks && bookmarks.length === 0 && (
              <div className="rounded-lg border border-dashed border-gray-300 py-10 text-center dark:border-gray-600">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  还没有书签。在学习内容里选中一段文字，点「添加书签」即可收藏当前位置。
                </p>
              </div>
            )}

            {bookmarks && bookmarks.length > 0 && (
              <div className="space-y-3">
                {bookmarks.map((b) => (
                  <div
                    key={b.id}
                    className="group flex items-stretch overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
                  >
                    <button
                      onClick={() => jump(b)}
                      className="min-w-0 flex-1 px-4 py-3 text-left"
                      title="跳转到对应内容"
                    >
                      <p className="line-clamp-1 border-l-2 border-amber-400 pl-2 text-xs text-gray-500 dark:text-gray-400">
                        {b.quote}
                      </p>
                      <p className="mt-1.5 line-clamp-2 text-sm text-gray-900 dark:text-gray-100">
                        {b.note || (
                          <span className="text-gray-400 dark:text-gray-500">（无备注）</span>
                        )}
                      </p>
                      <p className="mt-1.5 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                        <BookOpen className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">
                          {b.planTitle}
                          {b.moduleTitle ? ` · ${b.moduleTitle}` : ""}
                        </span>
                        <span className="shrink-0">
                          {new Date(b.createdAt).toLocaleDateString("zh-CN")}
                        </span>
                      </p>
                    </button>
                    <button
                      onClick={() => {
                        if (confirm("确定删除这条书签？")) {
                          deleteBookmark.mutate(
                            { planId: b.planId, annotationId: b.id },
                            {
                              onError: (e) =>
                                toast(`删除失败：${(e as Error).message}`, "error"),
                            },
                          );
                        }
                      }}
                      aria-label="删除书签"
                      className="flex w-10 shrink-0 items-center justify-center text-gray-300 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 dark:text-gray-600 dark:hover:bg-red-900/40 dark:hover:text-red-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {bookmarks && bookmarks.length > 0 && (
              <p className="mt-4 flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
                <Bookmark className="h-3.5 w-3.5" />
                点击书签跳转到学习内容中的对应位置
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
