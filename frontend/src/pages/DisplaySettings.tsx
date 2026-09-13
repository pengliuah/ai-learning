import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Type } from "lucide-react";
import {
  FONT_SIZE_OPTIONS,
  getFontSizeStep,
  setFontSizeStep,
  type FontSizeStep,
} from "../utils/fontSize";

export function DisplaySettings() {
  const [fontSize, setFontSize] = useState<FontSizeStep>(() => getFontSizeStep());

  return (
    <div className="mx-auto w-full max-w-5xl">
      <div className="mb-3 flex items-center gap-3">
        <Link
          to="/settings"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回设置
        </Link>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">显示设置</h1>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">
          <Type className="h-4 w-4" />
          界面字号
        </div>
        <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
          整体调整界面与正文的文字大小，仅对当前设备生效。
        </p>
        <div className="inline-flex rounded-md border border-gray-200 p-0.5 dark:border-gray-700">
          {FONT_SIZE_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => {
                setFontSize(opt.key);
                setFontSizeStep(opt.key);
              }}
              className={`rounded px-3 py-1.5 text-sm font-medium transition ${
                fontSize === opt.key
                  ? "bg-indigo-600 text-white dark:bg-indigo-500"
                  : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
