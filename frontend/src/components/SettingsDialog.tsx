import { useState, useRef, useEffect } from "react";
import { X, ChevronDown, Trash2, Check } from "lucide-react";
import {
  getApiBase,
  setApiBase,
  getApiBaseHistory,
  removeApiBaseHistory,
  PRESET_ENVS,
  DEFAULT_API_BASE,
} from "../api/client";

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(getApiBase());
  const [history, setHistory] = useState<string[]>(getApiBaseHistory());
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

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

  // History entries that are not already a preset URL (avoid duplicates)
  const presetUrls = new Set(PRESET_ENVS.map((e) => e.url));
  const customHistory = history.filter((u) => !presetUrls.has(u));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-lg dark:bg-gray-800" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">后端地址</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">
          选择或输入后端服务地址（含 /api），例如 {DEFAULT_API_BASE}
        </p>

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
              className="w-full rounded-l-md border border-r-0 border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              autoFocus
            />
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="inline-flex items-center rounded-r-md border border-gray-300 bg-gray-50 px-2 text-gray-500 hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600"
              title="选择环境"
              aria-label="选择环境"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>

          {open && (
            <div className="absolute z-10 mt-1 max-h-72 w-full overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800">
              {/* 预设环境 */}
              <p className="px-3 pb-1 pt-1.5 text-xs font-medium text-gray-400 dark:text-gray-500">预设环境</p>
              {PRESET_ENVS.map((env) => (
                <button
                  key={env.url}
                  type="button"
                  onClick={() => pick(env.url)}
                  className="flex w-full items-center justify-between px-3 py-1.5 text-left hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <span className="flex items-center gap-2">
                    {url === env.url ? (
                      <Check className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
                    ) : (
                      <span className="w-3.5" />
                    )}
                    <span className="text-sm text-gray-700 dark:text-gray-300">{env.label}</span>
                  </span>
                  <span className="truncate pl-3 text-xs text-gray-400 dark:text-gray-500">{env.url}</span>
                </button>
              ))}

              {/* 自定义历史地址 */}
              {customHistory.length > 0 && (
                <>
                  <div className="my-1 border-t border-gray-100 dark:border-gray-700" />
                  <p className="px-3 pb-1 pt-1.5 text-xs font-medium text-gray-400 dark:text-gray-500">历史地址</p>
                  {customHistory.map((u) => (
                    <div key={u} className="flex items-center justify-between px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700">
                      <button
                        type="button"
                        onClick={() => pick(u)}
                        className="flex flex-1 items-center gap-2 truncate text-left"
                        title={u}
                      >
                        {url === u ? (
                          <Check className="h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
                        ) : (
                          <span className="w-3.5 shrink-0" />
                        )}
                        <span className="truncate text-sm text-gray-700 dark:text-gray-300">{u}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(u)}
                        className="ml-2 shrink-0 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/40 dark:hover:text-red-400"
                        title="删除"
                        aria-label="删除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={reset} className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700">
            恢复默认
          </button>
          <button
            onClick={save}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
