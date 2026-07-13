import { apiRequest } from "./client";

export interface ProviderStatus {
  name: string;
  status: "healthy" | "unhealthy" | "degraded";
  details: string;
}

export interface PlatformMetrics {
  gpu_utilization: number;
  cpu_utilization: number;
  gpu_slots_active: number;
  gpu_slots_max: number;
  cpu_slots_active: number;
  cpu_slots_max: number;
  backlog_waiting_count: number;
  active_connections_db: number;
  queue_backlog_total: number;
}

export interface FeatureFlagRule {
  default: boolean;
  percentage: number;
  overrides: Record<string, boolean>;
  dev_override?: boolean | null;
}

export interface BackupResponse {
  success: boolean;
  snapshot_id: string;
  size_bytes: number;
  created_at: string;
}

export interface RestoreResponse {
  success: boolean;
  restored_at: string;
  details: string;
}

export interface PlatformOpsLog {
  id: string;
  workspace_id?: string | null;
  operator_id?: string | null;
  event_type: string;
  status: string;
  service_name: string;
  message: string;
  metadata_json: Record<string, any>;
  created_at: string;
}

export function getPlatformHealth() {
  return apiRequest<ProviderStatus[]>("/platform/health");
}

export function getPlatformMetrics() {
  return apiRequest<PlatformMetrics>("/platform/metrics");
}

export function scaleService(serviceName: string, replicas: number) {
  return apiRequest<{ message: string }>("/platform/scale", {
    method: "POST",
    body: { service_name: serviceName, replicas }
  });
}

export function getFeatureFlags() {
  return apiRequest<Record<string, FeatureFlagRule>>("/platform/flags");
}

export function updateFlagRollout(flagName: string, percentage: number) {
  return apiRequest<{ message: string }>("/platform/flags/percentage", {
    method: "POST",
    body: { flag_name: flagName, percentage }
  });
}

export function createFlagOverride(flagName: string, key: string, enabled: boolean) {
  return apiRequest<{ message: string }>("/platform/flags/override", {
    method: "POST",
    body: { flag_name: flagName, key, enabled }
  });
}

export function triggerPlatformBackup(snapshotName: string) {
  return apiRequest<BackupResponse>("/platform/backup", {
    method: "POST",
    body: { snapshot_name: snapshotName }
  });
}

export function triggerPlatformRestore(snapshotId: string) {
  return apiRequest<RestoreResponse>("/platform/restore", {
    method: "POST",
    body: { snapshot_id: snapshotId }
  });
}

export function getPlatformOpsLogs(workspaceId?: string, eventType?: string, limit: number = 50) {
  const q = new URLSearchParams();
  if (workspaceId) q.set("workspace_id", workspaceId);
  if (eventType) q.set("event_type", eventType);
  q.set("limit", String(limit));
  return apiRequest<PlatformOpsLog[]>(`/platform/logs?${q.toString()}`);
}
