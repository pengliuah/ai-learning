import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, KeyRound, Trash2, UserPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useUsers, useCreateUser, useDeleteUser, useResetUserPassword } from "../hooks/useAdmin";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";

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
