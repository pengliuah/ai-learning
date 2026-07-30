import { useState } from "react";
import { X, Check } from "lucide-react";
import { getApiBase, setApiBase, PRESET_ENVS, DEFAULT_API_BASE } from "../api/client";

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(getApiBase());

  const save = () => {
    setApiBase(url);
    window.location.reload();
  };

  const reset = () => {
    setApiBase("");
    window.location.reload();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-lg dark:bg-gray-800" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">后端环境</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 预设环境 */}
        <div className="space-y-2">
          {PRESET_ENVS.map((env) => {
            const active = url === env.url;
            return (
              <button
                key={env.url}
                type="button"
                onClick={() => setUrl(env.url)}
                className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-sm transition ${
                  active
                    ? "border-indigo-500 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-900/30"
                    : "border-gray-200 hover:border-gray-300 dark:border-gray-700 dark:hover:border-gray-600"
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="flex h-4 w-4 items-center justify-center">
                    {active && <Check className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />}
                  </span>
                  <span className="text-gray-900 dark:text-gray-100">{env.label}</span>
                </span>
                <span className="text-xs text-gray-400 dark:text-gray-500">{env.url}</span>
              </button>
            );
          })}
        </div>

        {/* 自定义地址 */}
        <div className="mt-4">
          <p className="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">自定义地址</p>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
            }}
            placeholder={DEFAULT_API_BASE}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            autoFocus
          />
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            含 /api 路径，无 http:// 前缀时自动补全
          </p>
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
