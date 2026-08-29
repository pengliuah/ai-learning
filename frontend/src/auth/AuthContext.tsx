import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getStoredUser } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  login: async () => {},
  logout: async () => {},
});

/**
 * 会话状态：localStorage 里的双 token + 当前用户。
 * - 登录后 api client 自动在请求头带 access token，401 时无感刷新。
 * - 登出调用后端吊销 refresh token，并清空 React Query 缓存
 *   （防止下一个用户看到上一个用户的请求数据）。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const queryClient = useQueryClient();

  const login = useCallback(
    async (username: string, password: string) => {
      const auth = await api.login(username, password);
      setUser(auth.user);
      queryClient.clear();
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
