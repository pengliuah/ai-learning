import type { ModuleStatus } from "../api/types";

const STATUS_MAP: Record<ModuleStatus, { label: string; className: string }> = {
  not_started: { label: "未开始", className: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  studying: { label: "学习中", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" },
  completed: { label: "已完成", className: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
};

export function StatusBadge({ status }: { status: ModuleStatus }) {
  const s = STATUS_MAP[status];
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${s.className}`}>
      {s.label}
    </span>
  );
}

const DIFFICULTY_MAP: Record<string, string> = {
  easy: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  hard: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const DIFFICULTY_LABEL: Record<string, string> = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

export function DifficultyBadge({ difficulty }: { difficulty: string }) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${DIFFICULTY_MAP[difficulty] || ""}`}>
      {DIFFICULTY_LABEL[difficulty] || difficulty}
    </span>
  );
}
