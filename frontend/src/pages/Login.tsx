import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Starfield } from "../components/Starfield";

export function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError((err as Error).message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-dvh overflow-hidden bg-[#0b1026]">
      {/* 全屏星空 */}
      <Starfield className="absolute inset-0 h-full w-full" />
      {/* 底部星空渐变，增强纵深 */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#141b3d]" />

      <div className="relative flex min-h-dvh items-center justify-center px-4 md:justify-end md:pr-[9%]">
        {/* 左侧标语（仅宽屏） */}
        <div className="pointer-events-none absolute left-[9%] hidden max-w-md select-none lg:block">
          <p className="text-3xl font-semibold leading-relaxed text-white/90">
            探索星空
            <span className="mx-3 inline-block animate-pulse">✨</span>
            点亮学习之旅
          </p>
          <p className="mt-4 text-sm leading-6 text-white/50">
            每一个学习目标，都是一颗待点亮的星。
            <br />
            登录智学助手，让 AI 教练陪你规划路径、生成内容、
            <br />
            完成测验——把整片星空逐一点亮。
          </p>
        </div>

        {/* 登录卡片：靠右 */}
        <form
          onSubmit={onSubmit}
          className="w-full max-w-sm rounded-2xl border border-white/15 bg-white/10 p-6 shadow-2xl backdrop-blur-xl"
        >
          <div className="mb-6 flex flex-col items-center gap-2">
            <div className="flex items-center gap-2 text-lg font-semibold text-white">
              <BookOpen className="h-5 w-5 text-indigo-300" />
              智学助手
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label htmlFor="login-username" className="mb-1 block text-sm font-medium text-white/80">
                用户名
              </label>
              <input
                id="login-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                className="w-full rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white placeholder-white/40 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                placeholder="输入用户名"
              />
            </div>
            <div>
              <label htmlFor="login-password" className="mb-1 block text-sm font-medium text-white/80">
                密码
              </label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="w-full rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white placeholder-white/40 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                placeholder="输入密码"
              />
            </div>

            {error && (
              <p className="rounded-md border border-red-400/30 bg-red-500/20 px-3 py-2 text-sm text-red-200">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={!username.trim() || !password || submitting}
              className="w-full rounded-md bg-indigo-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-indigo-900/40 transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "登录中..." : "进入星空"}
            </button>
          </div>

          <p className="mt-4 text-center text-xs text-white/40">
            没有账号？请联系管理员开通
          </p>
        </form>
      </div>
    </div>
  );
}
