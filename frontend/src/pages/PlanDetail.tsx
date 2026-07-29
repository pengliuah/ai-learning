import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronRight, Trash2, Clock } from "lucide-react";
import { usePlan, useDeletePlan, PLAN_KEYS } from "../hooks/usePlans";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge, DifficultyBadge } from "../components/StatusBadge";

const LEVEL_LABEL: Record<string, string> = {
  beginner: "入门",
  intermediate: "中级",
  advanced: "高级",
};

export function PlanDetail() {
  const { planId } = useParams();
  const navigate = useNavigate();
  const { data: doc, isLoading } = usePlan(planId);
  const deletePlan = useDeletePlan();

  if (isLoading) return <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>;
  if (!doc) return <p className="text-sm text-gray-500 dark:text-gray-400">计划不存在</p>;

  const { plan } = doc;
  const doneCount = plan.modules.filter((m) => m.status === "completed").length;
  const progress = plan.modules.length > 0 ? doneCount / plan.modules.length : 0;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回
        </button>
        <button
          onClick={() => {
            if (confirm(`删除「${plan.title}」？`)) {
              deletePlan.mutate(planId!, { onSuccess: () => navigate("/") });
            }
          }}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-gray-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/40 dark:hover:text-red-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{plan.title}</h1>
        {plan.summary && <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{plan.summary}</p>}
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">{plan.goal}</p>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
          <span>等级：{LEVEL_LABEL[plan.level] || plan.level}</span>
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {plan.totalMinutes} 分钟
          </span>
          <span>模块：{plan.modules.length}</span>
          <span>进度：{Math.round(progress * 100)}%</span>
        </div>
        <ProgressBar value={progress} className="mt-2" />
      </div>

      <div className="space-y-2">
        {plan.modules.map((module, idx) => (
          <button
            key={module.id}
            onClick={() => navigate(`/plans/${planId}/modules/${module.id}`)}
            className="flex w-full items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3 text-left hover:border-indigo-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-indigo-600"
          >
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400 dark:text-gray-500">{idx + 1}</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{module.title}</span>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <StatusBadge status={module.status} />
                <DifficultyBadge difficulty={module.difficulty} />
                <span className="text-xs text-gray-500 dark:text-gray-400">{module.minutes} 分钟</span>
              </div>
            </div>
            <ChevronRight className="h-4 w-4 text-gray-400 dark:text-gray-500" />
          </button>
        ))}
      </div>
    </div>
  );
}

// Re-export for convenience
export { PLAN_KEYS };
