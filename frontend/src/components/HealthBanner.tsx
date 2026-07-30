import { AlertTriangle, WifiOff } from "lucide-react";
import { useHealth } from "../hooks/usePlans";
import { getApiBase } from "../api/client";

export function HealthBanner() {
  const { data, isError } = useHealth();

  if (isError) {
    return (
      <div className="border-b border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/30">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2 text-sm text-amber-800 dark:text-amber-300">
          <WifiOff className="h-4 w-4 shrink-0" />
          <span>
            无法连接后端，请确认后端服务已启动
            <span className="ml-1 text-amber-600 dark:text-amber-400">({getApiBase()})</span>
          </span>
        </div>
      </div>
    );
  }

  if (data && !data.configured) {
    return (
      <div className="border-b border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/30">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2 text-sm text-amber-800 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          后端已连接，但未配置 ARK_API_KEY，生成功能不可用
        </div>
      </div>
    );
  }

  return null;
}
