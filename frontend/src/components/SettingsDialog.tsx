import { useState } from "react";
import { X } from "lucide-react";
import { getApiBase, setApiBase } from "../api/client";

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
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">后端地址</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-2 text-xs text-gray-500">
          输入后端服务的完整地址（含 /api），例如 http://192.168.1.100:8000/api
        </p>
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://ip:port/api"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          autoFocus
        />
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