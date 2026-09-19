import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Ban, Copy, KeyRound, Ticket, Trash2, UserPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useUsers, useCreateUser, useDeleteUser, useResetUserPassword } from "../hooks/useAdmin";
import { api, serverOrigin } from "../api/client";
import type { Invite } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";

/** 邀请码管理区块: 生成码 → 复制邀请链接发给对方; 列表可作废。 */
function InviteSection() {
  const { toast } = useToast();
  const [invites, setInvites] = useState<Invite[]>([]);
  const [maxUses, setMaxUses] = useState(1);
  const [expiresDays, setExpiresDays] = useState<number | null>(30);
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [lastCode, setLastCode] = useState<Invite | null>(null);

  const refresh = useCallback(async () => {
    try {
      setInvites(await api.listInvites());
    } catch {
      // 列表失败不打断页面
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const inv = await api.createInvite({ maxUses: maxUses, expiresDays: expiresDays, note });
      setLastCode(inv);
      setNote("");
      await refresh();
    } catch (err) {
      toast((err as Error).message || "生成失败", "error");
    } finally {
      setCreating(false);
    }
  };

  const inviteLink = (code: string) =>
    `${serverOrigin()}/register?code=${code}`;
  // 注意不能用 window.location.origin: App WebView 里是 https://localhost,
  // 复制出去的邀请链接在手机浏览器里打不开

  const copyLink = async (code: string) => {
    try {
      await navigator.clipboard.writeText(inviteLink(code));
      toast("邀请链接已复制", "success");
    } catch {
      toast(`复制失败，请手动复制：${inviteLink(code)}`, "error");
    }
  };

  const handleDisable = async (id: string) => {
    try {
      await api.disableInvite(id);
      await refresh();
    } catch (err) {
      toast((err as Error).message || "作废失败", "error");
    }
  };

  const inviteStatus = (inv: Invite): { label: string; cls: string } => {
    if (inv.disabled) return { label: "已作废", cls: "bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500" };
    if (inv.usedCount >= inv.maxUses)
      return { label: "已用尽", cls: "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400" };
    if (inv.expiresAt && new Date(inv.expiresAt) < new Date())
      return { label: "已过期", cls: "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400" };
    return { label: "可用", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300" };
  };

  return (
    <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">
        <Ticket className="h-4 w-4" />
        邀请码
        <span className="ml-1 text-xs font-normal text-gray-400">
          新用户凭邀请码在注册页自助建号
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={maxUses}
          onChange={(e) => setMaxUses(Number(e.target.value))}
          className="rounded-md border border-gray-300 bg-white px-2 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          title="可用次数"
        >
          <option value={1}>可用 1 次</option>
          <option value={5}>可用 5 次</option>
          <option value={10}>可用 10 次</option>
          <option value={50}>可用 50 次</option>
        </select>
        <select
          value={expiresDays ?? ""}
          onChange={(e) => setExpiresDays(e.target.value ? Number(e.target.value) : null)}
          className="rounded-md border border-gray-300 bg-white px-2 py-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          title="有效期"
        >
          <option value={7}>7 天有效</option>
          <option value={30}>30 天有效</option>
          <option value={90}>90 天有效</option>
          <option value="">永久有效</option>
        </select>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="备注（给谁用的）"
          maxLength={100}
          className="min-w-40 flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
        />
        <button
          onClick={() => void handleCreate()}
          disabled={creating}
          className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          生成邀请码
        </button>
      </div>

      {lastCode && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 dark:border-emerald-800 dark:bg-emerald-900/30">
          <span className="font-mono text-base font-semibold tracking-widest text-emerald-800 dark:text-emerald-300">
            {lastCode.code}
          </span>
          <button
            onClick={() => void copyLink(lastCode.code)}
            className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-white px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-100 dark:border-emerald-700 dark:bg-transparent dark:text-emerald-300 dark:hover:bg-emerald-900/50"
          >
            <Copy className="h-3.5 w-3.5" />
            复制邀请链接
          </button>
        </div>
      )}

      {invites.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-100 dark:divide-gray-700">
          {invites.slice(0, 10).map((inv) => {
            const st = inviteStatus(inv);
            return (
              <li key={inv.id} className="flex items-center gap-3 py-2">
                <span className="font-mono text-sm tracking-widest text-gray-800 dark:text-gray-200">
                  {inv.code}
                </span>
                <span className={`rounded px-1.5 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
                <span className="text-xs text-gray-400">
                  {inv.usedCount}/{inv.maxUses} 次
                  {inv.expiresAt ? ` · ${new Date(inv.expiresAt).toLocaleDateString()} 前有效` : " · 永久"}
                  {inv.note ? ` · ${inv.note}` : ""}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  {st.label === "可用" && (
                    <button
                      onClick={() => void copyLink(inv.code)}
                      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-indigo-600 dark:text-gray-400 dark:hover:bg-gray-700"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      复制链接
                    </button>
                  )}
                  {!inv.disabled && st.label === "可用" && (
                    <button
                      onClick={() => void handleDisable(inv.id)}
                      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400"
                    >
                      <Ban className="h-3.5 w-3.5" />
                      作废
                    </button>
                  )}
                </div>
              </li>
            );
          })}
          {invites.length > 10 && (
            <li className="py-2 text-xs text-gray-400">仅显示最近 10 条，共 {invites.length} 条</li>
          )}
        </ul>
      )}
    </div>
  );
}

export function AdminUsers() {
  const navigate = useNavigate();
  const { user: me } = useAuth();
  const { toast } = useToast();
  const { data: users, isLoading, isError } = useUsers();
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const resetPassword = useResetUserPassword();

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [makeAdmin, setMakeAdmin] = useState(false);
  const [resetTarget, setResetTarget] = useState<{ id: string; username: string } | null>(null);
  const [resetValue, setResetValue] = useState("");

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || !newPassword || createUser.isPending) return;
    try {
      await createUser.mutateAsync({
        username: newUsername.trim(),
        password: newPassword,
        role: makeAdmin ? "admin" : "user",
      });
      toast(`已创建用户 ${newUsername.trim()}`, "success");
      setNewUsername("");
      setNewPassword("");
      setMakeAdmin(false);
    } catch (err) {
      toast((err as Error).message || "创建失败", "error");
    }
  };

  const handleDelete = async (id: string, username: string) => {
    if (!confirm(`删除用户「${username}」及其全部学习数据？此操作不可恢复。`)) return;
    try {
      await deleteUser.mutateAsync(id);
      toast(`已删除用户 ${username}`, "success");
    } catch (err) {
      toast((err as Error).message || "删除失败", "error");
    }
  };

  const handleReset = async (e: FormEvent) => {
    e.preventDefault();
    if (!resetTarget || !resetValue) return;
    try {
      await resetPassword.mutateAsync({ id: resetTarget.id, newPassword: resetValue });
      toast(`已重置 ${resetTarget.username} 的密码`, "success");
      setResetTarget(null);
      setResetValue("");
    } catch (err) {
      toast((err as Error).message || "重置失败", "error");
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <div className="mb-3 flex items-center gap-3">
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回
        </button>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">用户管理</h1>
      </div>

      {/* 建号表单 */}
      <form
        onSubmit={handleCreate}
        className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
      >
        <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">
          <UserPlus className="h-4 w-4" />
          新建用户
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            placeholder="用户名（至少 2 个字符）"
            className="min-w-40 flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="初始密码（至少 6 位）"
            className="min-w-40 flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
          <label className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300">
            <input
              type="checkbox"
              checked={makeAdmin}
              onChange={(e) => setMakeAdmin(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            设为管理员
          </label>
          <button
            type="submit"
            disabled={!newUsername.trim() || newPassword.length < 6 || createUser.isPending}
            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            创建
          </button>
        </div>
      </form>

      {/* 邀请码 */}
      <InviteSection />

      {/* 重置密码弹层 */}
      {resetTarget && (
        <form
          onSubmit={handleReset}
          className="mb-6 rounded-lg border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-800 dark:bg-indigo-900/30"
        >
          <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <KeyRound className="h-4 w-4" />
            重置「{resetTarget.username}」的密码
          </div>
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={resetValue}
              onChange={(e) => setResetValue(e.target.value)}
              placeholder="新密码（至少 6 位）"
              autoFocus
              className="min-w-40 flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <button
              type="submit"
              disabled={resetValue.length < 6 || resetPassword.isPending}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
            >
              确认重置
            </button>
            <button
              type="button"
              onClick={() => {
                setResetTarget(null);
                setResetValue("");
              }}
              className="rounded-md px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
            >
              取消
            </button>
          </div>
          <p className="mt-2 text-xs text-indigo-600 dark:text-indigo-400">
            重置后该用户的所有登录会话将被吊销。
          </p>
        </form>
      )}

      {/* 用户列表 */}
      <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        {isLoading ? (
          <p className="p-4 text-sm text-gray-500 dark:text-gray-400">加载中...</p>
        ) : isError ? (
          <p className="p-4 text-sm text-red-600 dark:text-red-400">用户列表加载失败</p>
        ) : (
          <ul className="divide-y divide-gray-200 dark:divide-gray-700">
            {(users || []).map((u) => (
              <li key={u.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                    {u.username}
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        u.role === "admin"
                          ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300"
                          : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                      }`}
                    >
                      {u.role === "admin" ? "管理员" : "用户"}
                    </span>
                    {me?.id === u.id && (
                      <span className="text-xs text-gray-400">（当前登录）</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-400">
                    创建于 {new Date(u.createdAt).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={() => setResetTarget({ id: u.id, username: u.username })}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
                >
                  <KeyRound className="h-4 w-4" />
                  重置密码
                </button>
                <button
                  onClick={() => handleDelete(u.id, u.username)}
                  disabled={me?.id === u.id}
                  title={me?.id === u.id ? "不能删除当前登录的账号" : undefined}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm text-gray-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-red-900/30 dark:hover:text-red-400"
                >
                  <Trash2 className="h-4 w-4" />
                  删除
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
