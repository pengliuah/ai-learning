import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Bookmark, BookOpen, Trash2 } from "lucide-react";
import { useBookmarks, useDeleteBookmark } from "../hooks/usePlans";
import { useToast } from "../components/Toast";
import type { BookmarkItem } from "../api/types";

export function Bookmarks() {
  const navigate = useNavigate();
  const { data: bookmarks, isLoading } = useBookmarks();
  const deleteBookmark = useDeleteBookmark();
  const { toast } = useToast();

  const jump = (b: BookmarkItem) => {
    navigate(`/plans/${b.planId}/modules/${b.moduleId}?bookmark=${b.id}`);
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
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">我的书签</h1>
      </div>

      {isLoading && <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>}

      {bookmarks && bookmarks.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center dark:border-gray-600">
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
              <button onClick={() => jump(b)} className="min-w-0 flex-1 px-4 py-3 text-left" title="跳转到对应内容">
                <p className="line-clamp-1 border-l-2 border-amber-400 pl-2 text-xs text-gray-500 dark:text-gray-400">
                  {b.quote}
                </p>
                <p className="mt-1.5 line-clamp-2 text-sm text-gray-900 dark:text-gray-100">
                  {b.note || <span className="text-gray-400 dark:text-gray-500">（无备注）</span>}
                </p>
                <p className="mt-1.5 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                  <BookOpen className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">
                    {b.planTitle}
                    {b.moduleTitle ? ` · ${b.moduleTitle}` : ""}
                  </span>
                  <span className="shrink-0">{new Date(b.createdAt).toLocaleDateString("zh-CN")}</span>
                </p>
              </button>
              <button
                onClick={() => {
                  if (confirm("确定删除这条书签？")) {
                    deleteBookmark.mutate(
                      { planId: b.planId, annotationId: b.id },
                      { onError: (e) => toast(`删除失败：${(e as Error).message}`, "error") },
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
    </div>
  );
}
