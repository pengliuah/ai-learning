import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ImaSettings, ImaSettingsUpdate, GenSettings, GenSettingsUpdate, ModelSettings, ModelSettingsUpdate, UsageSummary, MemorySettingsUpdate } from "../api/types";

export const SETTINGS_KEYS = {
  ima: ["settings", "ima"] as const,
  regen: ["settings", "regen"] as const,
  model: ["settings", "model"] as const,
  usage: ["settings", "usage"] as const,
  memory: ["settings", "memory"] as const,
};

export const MEMORY_KEYS = {
  list: ["memories"] as const,
  profile: ["memories", "profile"] as const,
};

export function useUsageSummary() {
  return useQuery({
    queryKey: SETTINGS_KEYS.usage,
    queryFn: () => api.getUsageSummary(),
  });
}

export function useImaSettings() {
  return useQuery({
    queryKey: SETTINGS_KEYS.ima,
    queryFn: () => api.getImaSettings(),
  });
}

export function useUpdateImaSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ImaSettingsUpdate) => api.updateImaSettings(data),
    onSuccess: (data) => {
      qc.setQueryData(SETTINGS_KEYS.ima, data);
    },
  });
}

export function useRegenSettings() {
  return useQuery({
    queryKey: SETTINGS_KEYS.regen,
    queryFn: () => api.getRegenSettings(),
  });
}

export function useUpdateRegenSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: GenSettingsUpdate) => api.updateRegenSettings(data),
    onSuccess: (data) => {
      qc.setQueryData(SETTINGS_KEYS.regen, data);
    },
  });
}

export function useModelSettings() {
  return useQuery({
    queryKey: SETTINGS_KEYS.model,
    queryFn: () => api.getModelSettings(),
  });
}

export function useUpdateModelSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ModelSettingsUpdate) => api.updateModelSettings(data),
    onSuccess: (data) => {
      qc.setQueryData(SETTINGS_KEYS.model, data);
      qc.invalidateQueries({ queryKey: ["health"] });
    },
  });
}

export function useMemorySettings() {
  return useQuery({
    queryKey: SETTINGS_KEYS.memory,
    queryFn: () => api.getMemorySettings(),
  });
}

export function useUpdateMemorySettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MemorySettingsUpdate) => api.updateMemorySettings(data),
    onSuccess: (data) => {
      qc.setQueryData(SETTINGS_KEYS.memory, data);
    },
  });
}

export function useMemories() {
  return useQuery({
    queryKey: MEMORY_KEYS.list,
    queryFn: () => api.listMemories(),
  });
}

export function useUpdateMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memoryId, memory }: { memoryId: string; memory: string }) =>
      api.updateMemory(memoryId, memory),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MEMORY_KEYS.list });
    },
  });
}

export function useMemoryProfile() {
  return useQuery({
    queryKey: MEMORY_KEYS.profile,
    queryFn: () => api.getMemoryProfile(),
  });
}

export function useUpdateMemoryProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profile: string) => api.updateMemoryProfile(profile),
    onSuccess: (data) => {
      qc.setQueryData(MEMORY_KEYS.profile, data);
    },
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: string) => api.deleteMemory(memoryId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MEMORY_KEYS.list });
    },
  });
}
