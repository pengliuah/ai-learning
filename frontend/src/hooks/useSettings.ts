import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ImaSettings, ImaSettingsUpdate, GenSettings, GenSettingsUpdate, ModelSettings, ModelSettingsUpdate } from "../api/types";

export const SETTINGS_KEYS = {
  ima: ["settings", "ima"] as const,
  regen: ["settings", "regen"] as const,
  model: ["settings", "model"] as const,
};

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
