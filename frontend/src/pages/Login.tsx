import { lazy, Suspense, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Starfield } from "../components/Starfield";

// 3D 太空场景（地球/月球/银河）单独分包，进登录页时再加载；
// 加载期间或 WebGL 不可用时，底下的 2D 星空直接顶上。
const SpaceScene = lazy(() =>
  import("../components/SpaceScene").then((m) => ({ default: m.SpaceScene })),
);

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
    <div className="relative min-h-dvh overflow-hidden bg-[#05070f]">
      {/* 底层：2D 闪烁星空 + 流星（3D 场景加载前后都在） */}
      <Starfield className="absolute inset-0 h-full w-full" />
      {/* 上层：three.js 地球 / 月球 / 银河（透明背景） */}
      <Suspense fallback={null}>
        <SpaceScene className="absolute inset-0 h-full w-full" />
      </Suspense>
      {/* 暗角，压暗四周突出主体 */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_45%,rgba(3,6,18,0.5)_100%)]" />

      <div className="relative z-10 flex min-h-dvh items-center justify-center px-4 md:justify-end md:pr-[9%]">
        {/* 左侧标语（仅宽屏） */}
        <div className="pointer-events-none absolute left-[9%] hidden max-w-md select-none lg:block">
          <p className="bg-gradient-to-r from-white via-indigo-100 to-indigo-300 bg-clip-text text-3xl font-semibold leading-relaxed text-transparent">
            从地球出发
            <span className="mx-3 inline-block animate-pulse">🚀</span>
            探索知识星系
          </p>
          <p className="mt-4 text-sm leading-6 text-white/55">
            每一个学习目标，都是一颗待点亮的星。
            <br />
            登录智学助手，让 AI 教练陪你规划路径、生成内容、
            <br />
            完成测验——从这颗蓝色星球出发，把整片星系逐一点亮。
          </p>
        </div>

        {/* 登录卡片：靠右，深色玻璃质感 */}
        <form
          onSubmit={onSubmit}
          className="relative w-full max-w-sm rounded-2xl border border-white/10 bg-[#0a1128]/60 p-6 shadow-[0_0_80px_-20px_rgba(99,102,241,0.55)] backdrop-blur-2xl"
        >
          {/* 卡片顶部高光线 */}
          <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-indigo-300/60 to-transparent" />

          <div className="mb-6 flex flex-col items-center gap-2">
            <div className="flex items-center gap-2 text-lg font-semibold">
              <BookOpen className="h-5 w-5 text-indigo-300" />
              <span className="bg-gradient-to-r from-indigo-200 via-white to-violet-200 bg-clip-text text-transparent">
                智学助手
              </span>
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
                className="w-full rounded-md border border-white/15 bg-white/[0.06] px-3 py-2 text-sm text-white placeholder-white/40 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
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
                className="w-full rounded-md border border-white/15 bg-white/[0.06] px-3 py-2 text-sm text-white placeholder-white/40 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300"
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
              className="w-full rounded-md bg-gradient-to-r from-indigo-500 to-violet-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-indigo-900/50 transition hover:from-indigo-400 hover:to-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "登录中..." : "登录"}
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
