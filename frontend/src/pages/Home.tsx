import { Link } from "react-router-dom";
import { Plus, Trash2, Clock } from "lucide-react";
import { usePlans, useDeletePlan } from "../hooks/usePlans";
import { ProgressBar } from "../components/ProgressBar";

export function Home() {
  const { data: plans, isLoading } = usePlans();
  const deletePlan = useDeletePlan();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold">学习计划</h1>
        <Link
          to="/plans/new"
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus className="h-4 w-4" />
          新建计划
        </Link>
      </div>

      {isLoading && <p className="text-sm text-gray-500">加载中...</p>}

      {plans && plans.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center">
          <p className="text-sm text-gray-500">还没有学习计划，点击“新建计划”开始</p>
        </div>
      )}

      {plans && plans.length > 0 && (
        <div className="space-y-3">
          {plans.map((plan) => (
            <div
              key={plan.id}
              className="group flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3 hover:border-indigo-300"
            >
              <Link to={`/plans/${plan.id}`} className="flex-1">
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <p className="font-medium text-gray-900">{plan.title}</p>
                    <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                      <span>{new Date(plan.createdAt).toLocaleDateString("zh-CN")}</span>
                      <span>{Math.round(plan.progress * 100)}%</span>
                    </div>
                    <ProgressBar value={plan.progress} className="mt-2 max-w-xs" />
                  </div>
                </div>
              </Link>
              <button
                onClick={() => {
                  if (confirm(`删除「${plan.title}」？`)) deletePlan.mutate(plan.id);
                }}
                className="ml-3 rounded p-1.5 text-gray-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
