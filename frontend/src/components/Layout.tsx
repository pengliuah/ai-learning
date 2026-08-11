import { Link } from "react-router-dom";
import { BookOpen, Sun, Moon, Bot } from "lucide-react";
import { HealthBanner } from "./HealthBanner";
import { useTheme } from "../hooks/useTheme";

export function Layout({ children }: { children: React.ReactNode }) {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="mx-auto flex h-12 max-w-5xl items-center gap-2 px-4">
          <Link to="/" className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
            <BookOpen className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
            智学助手
          </Link>
          <Link
            to="/coach"
            className="ml-4 inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400"
          >
            <Bot className="h-4 w-4" />
            AI 教练
          </Link>
          <button
            onClick={toggleTheme}
            className="ml-auto rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            title={theme === "dark" ? "切换日间模式" : "切换夜间模式"}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </header>
      <HealthBanner />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}