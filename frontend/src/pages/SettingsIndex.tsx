import { Link } from "react-router-dom";
import {
  ArrowLeft, BookmarkPlus, ChevronRight, KeyRound, RefreshCw, Settings2, Type,
} from "lucide-react";

const ITEMS = [
  {
    to: "/settings/model",
    icon: Settings2,
    title: "模型设置",
    desc: "API Key、模型、生成参数与 Token 用量统计",
  },
  {
    to: "/settings/display",
    icon: Type,
    title: "显示设置",
    desc: "界面字号整体调整",
  },
  {
    to: "/settings/regenerate",
    icon: RefreshCw,
    title: "重新生成设置",
    desc: "计划 / 内容 / 测验的生成策略与批改评分策略提示词",
  },
  {
    to: "/settings/ima",
    icon: BookmarkPlus,
    title: "IMA 设置",
    desc: "保存到 IMA 的凭证与技能提示词",
  },
  {
    to: "/settings/account",
    icon: KeyRound,
    title: "账号设置",
    desc: "修改登录密码",
  },
];

export function SettingsIndex() {
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
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">设置</h1>
      </div>

      <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white dark:divide-gray-700 dark:border-gray-700 dark:bg-gray-800">
        {ITEMS.map(({ to, icon: Icon, title, desc }) => (
          <Link
            key={to}
            to={to}
            className="flex items-center gap-3 px-4 py-3.5 transition hover:bg-gray-50 dark:hover:bg-gray-700/50"
          >
            <Icon className="h-4.5 w-4.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-gray-900 dark:text-gray-100">{title}</span>
              <span className="block text-xs text-gray-500 dark:text-gray-400">{desc}</span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-gray-300 dark:text-gray-600" />
          </Link>
        ))}
      </div>
    </div>
  );
}
