import { Link } from "react-router-dom";
import { BookOpen, Sun, Moon, Bot, Settings, Users, LogOut } from "lucide-react";
import { HealthBanner } from "./HealthBanner";
import { useTheme } from "../hooks/useTheme";
import { useAuth } from "../auth/AuthContext";

export function Layout({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
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

          <div className="ml-auto flex items-center gap-1">
            {user?.role === "admin" && (
              <Link
                to="/admin/users"
                className="inline-flex items-center gap-1.5 rounded p-1.5 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                title="用户管理"
              >
                <Users className="h-4 w-4" />
              </Link>
            )}
            <button
              onClick={toggleTheme}
              className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
              title={theme === "dark" ? "切换日间模式" : "切换夜间模式"}
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <Link
              to="/settings"
              className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
              title="设置"
            >
              <Settings className="h-4 w-4" />
            </Link>
            {user && (
              <span className="flex items-center gap-1 pl-1 text-sm text-gray-500 dark:text-gray-400">
                <Link
                  to="/bookmarks"
                  className="max-w-24 truncate rounded px-1 py-0.5 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                  title="我的记录"
                >
                  {user.username}
                </Link>
                <button
                  onClick={() => logout()}
                  className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                  title="退出登录"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </span>
            )}
          </div>
        </div>
      </header>
      <div className="shrink-0">
        <HealthBanner />
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* 滚动容器通栏，滚动条贴窗口最右侧；限宽交给内层。
            内层必须 min-h-0：否则教练页等自带滚动区的页面在内容变长时，
            这一层会被内容撑高，出现外层+内层两条滚动条。
            wide 变体（教练页等自带滚动区的页面）：内层不限宽，
            页面的滚动条才贴窗口边缘，内容由页面自己控制宽度。 */}
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {wide ? (
            <div className="flex min-h-0 w-full flex-1 flex-col">{children}</div>
          ) : (
            <div className="mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col px-4 py-6">
              {children}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
