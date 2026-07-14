import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export const PLAN_KEYS = {
  list: ["plans"] as const,
  detail: (id: string) => ["plan", id] as const,
};

export function usePlans() {
  return useQuery({
    queryKey: PLAN_KEYS.list,
    queryFn: api.listPlans,
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


export function useHealth() {
  return useQuery({
    queryKey: ["health"] as const,
    queryFn: api.health,
    refetchInterval: 15000,
    retry: false,
  });
}
