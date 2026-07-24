import { useState, useRef, useEffect } from "react";
import { X, ChevronDown, Trash2 } from "lucide-react";
import {
  getApiBase,
  setApiBase,
  getApiBaseHistory,
  removeApiBaseHistory,
  DEFAULT_API_BASE,
} from "../api/client";

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(getApiBase());
  const [history, setHistory] = useState<string[]>(getApiBaseHistory());
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // 点击下拉外部时收起历史地址面板
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const save = () => {
    setApiBase(url);
    window.location.reload();
  };

  const reset = () => {
    setApiBase("");
    window.location.reload();
  };

  const pick = (u: string) => {
    setUrl(u);
    setOpen(false);
  };

  const remove = (u: string) => {
    removeApiBaseHistory(u);
    setHistory(getApiBaseHistory());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">后端地址</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-2 text-xs text-gray-500">
          输入后端服务的完整地址（含 /api），例如 {DEFAULT_API_BASE}
        </p>

        {/* 输入框 + 历史地址下拉 */}
        <div className="relative" ref={boxRef}>
          <div className="flex">
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
              }}
              placeholder={DEFAULT_API_BASE}
              className="w-full rounded-l-md border border-r-0 border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="inline-flex items-center rounded-r-md border border-gray-300 bg-gray-50 px-2 text-gray-500 hover:bg-gray-100"
              title="历史地址"
              aria-label="历史地址"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>

          {open && (
            <div className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg">
              {history.length === 0 ? (
                <p className="px-3 py-2 text-xs text-gray-400">暂无历史地址</p>
              ) : (
                history.map((u) => (
                  <div key={u} className="flex items-center justify-between px-3 py-1.5 hover:bg-gray-50">
                    <button
                      type="button"
                      onClick={() => pick(u)}
                      className="flex-1 truncate text-left text-sm text-gray-700"
                      title={u}
                    >
                      {u}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(u)}
                      className="ml-2 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                      title="删除"
                      aria-label="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={reset} className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
            恢复默认
          </button>
          <button
            onClick={save}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}