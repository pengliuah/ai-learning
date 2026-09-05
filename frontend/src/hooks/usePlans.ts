import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Annotation, BookmarkItem } from "../api/types";

export const PLAN_KEYS = {
  list: ["plans"] as const,
  detail: (id: string) => ["plan", id] as const,
};

export const ANNOTATION_KEYS = {
  module: (planId: string, moduleId: string) => ["annotations", planId, moduleId] as const,
  all: ["bookmarks"] as const,
};

// 书签列表（跨计划/模块聚合）
export function useBookmarks() {
  return useQuery({
    queryKey: ANNOTATION_KEYS.all,
    queryFn: () => api.listBookmarks(),
  });
}

// 从书签列表删除：乐观移除该项，失败回滚重取
export function useDeleteBookmark() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, annotationId }: { planId: string; annotationId: string }) =>
      api.deleteAnnotation(planId, annotationId),
    onSuccess: (_data, variables) => {
      qc.setQueryData<BookmarkItem[] | undefined>(ANNOTATION_KEYS.all, (old) =>
        (old ?? []).filter((b) => b.id !== variables.annotationId),
      );
      qc.invalidateQueries({ queryKey: ANNOTATION_KEYS.all });
    },
  });
}

export function useAnnotations(planId: string, moduleId: string) {
  return useQuery({
    queryKey: ANNOTATION_KEYS.module(planId, moduleId),
    queryFn: () => api.listAnnotations(planId, moduleId),
  });
}

export function useCreateAnnotation(planId: string, moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { quote: string; prefix: string; suffix: string; note: string }) =>
      api.createAnnotation(planId, moduleId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ANNOTATION_KEYS.module(planId, moduleId) }),
  });
}

export function useUpdateAnnotation(planId: string, moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ annotationId, note }: { annotationId: string; note: string }) =>
      api.updateAnnotation(planId, annotationId, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ANNOTATION_KEYS.module(planId, moduleId) }),
  });
}

export function useDeleteAnnotation(planId: string, moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (annotationId: string) => api.deleteAnnotation(planId, annotationId),
    onSuccess: (_data, annotationId) => {
      // 乐观移除：不等 refetch 完成，立即让高亮/卡片/虚线消失
      qc.setQueryData<{ id: string }[] | undefined>(
        ANNOTATION_KEYS.module(planId, moduleId),
        (old) => (old ?? []).filter((a) => a.id !== annotationId),
      );
      qc.invalidateQueries({ queryKey: ANNOTATION_KEYS.module(planId, moduleId) });
    },
  });
}

export function usePlans() {
  return useQuery({
    queryKey: PLAN_KEYS.list,
    queryFn: () => api.listPlans(),
  });
}

export function usePlan(planId: string | undefined) {
  return useQuery({
    queryKey: PLAN_KEYS.detail(planId!),
    queryFn: () => api.getPlan(planId!),
    enabled: !!planId,
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ input, mode }: { input: string; mode: "topic" | "materials" }) =>
      api.createPlan(input, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PLAN_KEYS.list });
    },
  });
}

export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (planId: string) => api.deletePlan(planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PLAN_KEYS.list });
    },
  });
}

export function useGenerateQuiz() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, moduleId }: { planId: string; moduleId: string }) =>
      api.generateQuiz(planId, moduleId),
    onSuccess: (doc) => {
      qc.setQueryData(PLAN_KEYS.detail(doc.id), doc);
    },
  });
}

export function useGradeQuiz() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, moduleId }: { planId: string; moduleId: string }) =>
      api.gradeQuiz(planId, moduleId),
    onSuccess: (doc) => {
      qc.setQueryData(PLAN_KEYS.detail(doc.id), doc);
    },
  });
}

export function useSaveAnswers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      moduleId,
      answers,
    }: {
      planId: string;
      moduleId: string;
      answers: Record<string, string>;
    }) => api.saveAnswers(planId, moduleId, answers),
    onSuccess: (doc) => {
      qc.setQueryData(PLAN_KEYS.detail(doc.id), doc);
    },
  });
}

export function usePatchModule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      moduleId,
      status,
    }: {
      planId: string;
      moduleId: string;
      status: string;
    }) => api.patchModule(planId, moduleId, status),
    onSuccess: (doc) => {
      qc.setQueryData(PLAN_KEYS.detail(doc.id), doc);
    },
  });
}

// 手工编辑学习内容正文：后端返回完整 Document，直接替换缓存即可
export function useUpdateContent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      moduleId,
      markdown,
    }: {
      planId: string;
      moduleId: string;
      markdown: string;
    }) => api.updateContent(planId, moduleId, markdown),
    onSuccess: (doc) => {
      qc.setQueryData(PLAN_KEYS.detail(doc.id), doc);
    },
  });
}

// 首页计划列表拖拽排序：本地先重排（乐观更新），保存失败回滚重取
export function useReorderPlans() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (planIds: string[]) => api.reorderPlans(planIds),
    onSuccess: (items) => {
      qc.setQueryData(PLAN_KEYS.list, items);
    },
    onError: () => {
      qc.invalidateQueries({ queryKey: PLAN_KEYS.list });
    },
  });
}


export function useSaveToIma() {
  return useMutation({
    mutationFn: ({
      planId,
      moduleId,
      contentType,
    }: {
      planId: string;
      moduleId?: string;
      contentType?: "plan" | "content" | "quiz" | "result";
    }) =>
      api.saveToIma(planId, { moduleId, contentType }),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"] as const,
    queryFn: api.health,
    refetchInterval: 300000,  // 5 分钟
    retry: false,
  });
}
