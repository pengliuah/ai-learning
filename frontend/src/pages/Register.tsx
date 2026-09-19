import { lazy, Suspense, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { BookOpen } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Starfield } from "../components/Starfield";

// 3D 太空场景与登录页共用（同款懒加载 + 2D 星空兜底）
const SpaceScene = lazy(() =>
  import("../components/SpaceScene").then((m) => ({ default: m.SpaceScene })),
);

/** 邀请制注册页: 管理员发的邀请链接 (?code=xxx) 带码进入, 码自动填好。 */
export function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [inviteCode, setInviteCode] = useState(
    () => (searchParams.get("code") || "").trim().toUpperCase(),
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password || !inviteCode.trim() || submitting) return;
    if (password.length < 6) {
      setError("密码至少 6 位");
      return;
    }
    if (password !== password2) {
      setError("两次输入的密码不一致");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await register(username.trim(), password, inviteCode.trim());
      navigate("/", { replace: true });
    } catch (err) {
      setError((err as Error).message || "注册失败");
    } finally {
      setSubmitting(false);
    }
  };

  const inputCls =
    "w-full rounded-md border border-white/15 bg-white/[0.06] px-3 py-2 text-sm text-white placeholder-white/40 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300";

  return (
    <div className="relative min-h-dvh overflow-hidden bg-[#05070f]">
      <Starfield className="absolute inset-0 h-full w-full" />
      <Suspense fallback={null}>
        <SpaceScene className="absolute inset-0 h-full w-full" />
      </Suspense>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_45%,rgba(3,6,18,0.5)_100%)]" />

      <div className="relative z-10 flex min-h-dvh items-center justify-center px-4 md:justify-end md:pr-[9%]">
        <div className="pointer-events-none absolute left-[9%] hidden max-w-md select-none lg:block">
          <p className="bg-gradient-to-r from-white via-indigo-100 to-indigo-300 bg-clip-text text-3xl font-semibold leading-relaxed text-transparent">
            凭邀请码
            <span className="mx-3 inline-block animate-pulse">🎟️</span>
            登上知识飞船
          </p>
          <p className="mt-4 text-sm leading-6 text-white/70 [text-shadow:0_1px_10px_rgba(0,0,0,0.9),0_0_3px_rgba(0,0,0,0.7)]">
            本站采用邀请制。向管理员索取邀请码，
            <br />
            即可创建自己的账号，开始你的学习旅程。
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="relative w-full max-w-sm rounded-2xl border border-white/10 bg-[#0a1128]/60 p-6 shadow-[0_0_80px_-20px_rgba(99,102,241,0.55)] backdrop-blur-2xl"
        >
          <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-indigo-300/60 to-transparent" />

          <div className="mb-6 flex flex-col items-center gap-2">
            <div className="flex items-center gap-2 text-lg font-semibold">
              <BookOpen className="h-5 w-5 text-indigo-300" />
              <span className="bg-gradient-to-r from-indigo-200 via-white to-violet-200 bg-clip-text text-transparent">
                创建账号
              </span>
            </div>
            <p className="text-xs text-white/40">邀请制注册，邀请码向管理员索取</p>
          </div>

          <div className="space-y-4">
            <div>
              <label htmlFor="reg-invite" className="mb-1 block text-sm font-medium text-white/80">
                邀请码
              </label>
              <input
                id="reg-invite"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                autoFocus={!inviteCode}
                className={`${inputCls} font-mono tracking-widest uppercase`}
                placeholder="8 位邀请码"
                maxLength={8}
              />
            </div>
            <div>
              <label htmlFor="reg-username" className="mb-1 block text-sm font-medium text-white/80">
                用户名
              </label>
              <input
                id="reg-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                className={inputCls}
                placeholder="2-32 个字符"
                maxLength={32}
              />
            </div>
            <div>
              <label htmlFor="reg-password" className="mb-1 block text-sm font-medium text-white/80">
                密码
              </label>
              <input
                id="reg-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                className={inputCls}
                placeholder="至少 6 位"
              />
            </div>
            <div>
              <label htmlFor="reg-password2" className="mb-1 block text-sm font-medium text-white/80">
                确认密码
              </label>
              <input
                id="reg-password2"
                type="password"
                value={password2}
                onChange={(e) => setPassword2(e.target.value)}
                autoComplete="new-password"
                className={inputCls}
                placeholder="再输入一次"
              />
            </div>

            {error && (
              <p className="rounded-md border border-red-400/30 bg-red-500/20 px-3 py-2 text-sm text-red-200">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={!username.trim() || !password || !password2 || !inviteCode.trim() || submitting}
              className="w-full rounded-md bg-gradient-to-r from-indigo-500 to-violet-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-indigo-900/50 transition hover:from-indigo-400 hover:to-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "注册中..." : "注册并进入"}
            </button>
          </div>

          <p className="mt-4 text-center text-xs text-white/40">
            已有账号？{" "}
            <Link to="/login" className="text-indigo-300 hover:text-indigo-200">
              去登录
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
