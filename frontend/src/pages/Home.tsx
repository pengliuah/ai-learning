import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, useSortable, arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { usePlans, useDeletePlan, useReorderPlans, PLAN_KEYS } from "../hooks/usePlans";
import { useToast } from "../components/Toast";
import { ProgressBar } from "../components/ProgressBar";
import type { PlanListItem } from "../api/types";

export function Home() {
  const { data: plans, isLoading } = usePlans();
  const deletePlan = useDeletePlan();
  const reorderPlans = useReorderPlans();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  // distance=8：按下移动 8px 才算拖动，避免轻点/滚动误触发；触屏同样适用
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  // 拖拽结束：本地先重排（乐观更新），再提交后端持久化；失败回滚重取
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !plans) return;
    const oldIndex = plans.findIndex((p) => p.id === active.id);
    const newIndex = plans.findIndex((p) => p.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const next = arrayMove(plans, oldIndex, newIndex);
    queryClient.setQueryData(PLAN_KEYS.list, next);
    reorderPlans.mutate(next.map((p) => p.id), {
      onSuccess: () => toast("顺序已保存", "success"),
      onError: () => toast("排序保存失败，已恢复", "error"),
    });
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">学习计划</h1>
        <Link
          to="/plans/new"
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600"
        >
          <Plus className="h-4 w-4" />
          新建计划
        </Link>
      </div>

      {isLoading && <p className="text-sm text-gray-500 dark:text-gray-400">加载中...</p>}

      {plans && plans.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center dark:border-gray-600">
          <p className="text-sm text-gray-500 dark:text-gray-400">还没有学习计划，点击“新建计划”开始</p>
        </div>
      )}

      {plans && plans.length > 0 && (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={plans.map((p) => p.id)} strategy={verticalListSortingStrategy}>
            <div className="space-y-3">
              {plans.map((plan) => (
                <SortablePlanCard
                  key={plan.id}
                  plan={plan}
                  onDelete={() => {
                    if (confirm(`删除「${plan.title}」？`)) deletePlan.mutate(plan.id);
                  }}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  );
}

// ============================================================
// SortablePlanCard — 计划卡片，左侧拖动手柄 + 右侧点击进入/删除
// ============================================================
function SortablePlanCard({ plan, onDelete }: { plan: PlanListItem; onDelete: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: plan.id,
  });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`group flex items-center rounded-lg border bg-white px-3 py-3 ${
        isDragging
          ? "relative z-10 border-indigo-400 shadow-lg dark:border-indigo-500"
          : "border-gray-200 hover:border-indigo-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-indigo-600"
      }`}
    >
      {/* 拖动手柄：与点击区域分离，touch-none 保证手机上拖得动 */}
      <button
        {...attributes}
        {...listeners}
        aria-label="拖动排序"
        title="拖动排序"
        className="flex w-7 shrink-0 cursor-grab touch-none items-center justify-center self-stretch text-gray-300 hover:text-gray-500 active:cursor-grabbing dark:text-gray-600 dark:hover:text-gray-400"
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <Link to={`/plans/${plan.id}`} className="min-w-0 flex-1">
        <p className="font-medium text-gray-900 dark:text-gray-100">{plan.title}</p>
        <div className="mt-1 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span>{new Date(plan.createdAt).toLocaleDateString("zh-CN")}</span>
          <span>{Math.round(plan.progress * 100)}%</span>
        </div>
        <ProgressBar value={plan.progress} className="mt-2 max-w-xs" />
      </Link>
      <button
        onClick={onDelete}
        className="ml-3 rounded p-1.5 text-gray-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 dark:hover:bg-red-900/40 dark:hover:text-red-400"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}
