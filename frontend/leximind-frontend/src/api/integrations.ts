import { apiRequest } from "./client";

export interface ConnectorType {
  type: string;
  name: string;
  category: string;
  description: string;
  icon: string;
  capabilities: string[];
  auth_type: string;
  version: string;
  status: string;
}

export interface ConnectorInstance {
  id: string;
  workspace_id: string;
  connector_type: string;
  display_name: string;
  category: string;
  config: Record<string, any>;
  is_active: boolean;
  status: string;
  health: string;
  last_sync_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface WebhookEndpoint {
  id: string;
  workspace_id: string;
  name: string;
  direction: string;
  url: string;
  secret?: string;
  event_filter: string[];
  is_active: boolean;
  retry_policy: Record<string, any>;
  created_at: string;
}

export interface AutomationWorkflow {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  trigger: { type: string; pattern?: string; schedule?: string; [key: string]: any };
  conditions: Array<{ field: string; operator: string; value: any }>;
  actions: Array<{ type: string; config: Record<string, any> }>;
  is_active: boolean;
  execution_count: number;
  last_executed_at: string | null;
  created_at: string;
}

export interface AutomationExecution {
  id: string;
  workflow_id: string;
  workspace_id: string;
  trigger_event_id: string | null;
  status: string;
  steps_completed: number;
  steps_total: number;
  duration_ms: number;
  result: Record<string, any>;
  error: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ScheduledJob {
  id: string;
  workspace_id: string;
  name: string;
  job_type: string;
  schedule: string;
  config: Record<string, any>;
  is_active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface MCPServerRegistration {
  id: string;
  workspace_id: string;
  name: string;
  server_url: string;
  transport: string;
  auth_config: Record<string, any>;
  status: string;
  health: string;
  last_synced_at: string | null;
  created_at: string;
}

export interface IntegrationEvent {
  id: string;
  workspace_id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

// Connector Types
export function listConnectorTypes(workspaceId: string) {
  return apiRequest<ConnectorType[]>(`/workspaces/${workspaceId}/integrations/connectors/types`);
}

// Connector Instances
export function listConnectorInstances(workspaceId: string) {
  return apiRequest<ConnectorInstance[]>(`/workspaces/${workspaceId}/integrations/connectors`);
}

export function installConnector(workspaceId: string, payload: { connector_type: string; display_name: string; config: Record<string, any> }) {
  return apiRequest<ConnectorInstance>(`/workspaces/${workspaceId}/integrations/connectors`, {
    method: "POST",
    body: payload,
  });
}

export function deleteConnector(workspaceId: string, connectorId: string) {
  return apiRequest<void>(`/workspaces/${workspaceId}/integrations/connectors/${connectorId}`, {
    method: "DELETE",
  });
}

export function configureConnectorAuth(workspaceId: string, connectorId: string, payload: { auth_type: string; credentials: Record<string, any>; scopes?: string[] }) {
  return apiRequest<{ is_valid: boolean; message: string }>(`/workspaces/${workspaceId}/integrations/connectors/${connectorId}/auth`, {
    method: "POST",
    body: payload,
  });
}

export function browseConnector(workspaceId: string, connectorId: string, payload: { path: string; page_size?: number; cursor?: string }) {
  return apiRequest<{ items: any[]; next_cursor: string; total_items: number }>(`/workspaces/${workspaceId}/integrations/connectors/${connectorId}/browse`, {
    method: "POST",
    body: payload,
  });
}

export function syncConnector(workspaceId: string, connectorId: string, payload: { resource_types: string[]; full_sync?: boolean }) {
  return apiRequest<{ status: string; items_synced: number; error: string | null }>(`/workspaces/${workspaceId}/integrations/connectors/${connectorId}/sync`, {
    method: "POST",
    body: payload,
  });
}

// Webhooks
export function listWebhooks(workspaceId: string) {
  return apiRequest<WebhookEndpoint[]>(`/workspaces/${workspaceId}/integrations/webhooks`);
}

export function createWebhook(workspaceId: string, payload: { name: string; direction: string; url?: string; event_filter: string[] }) {
  return apiRequest<WebhookEndpoint>(`/workspaces/${workspaceId}/integrations/webhooks`, {
    method: "POST",
    body: payload,
  });
}

export function deleteWebhook(workspaceId: string, webhookId: string) {
  return apiRequest<void>(`/workspaces/${workspaceId}/integrations/webhooks/${webhookId}`, {
    method: "DELETE",
  });
}

// Workflows
export function listWorkflows(workspaceId: string) {
  return apiRequest<AutomationWorkflow[]>(`/workspaces/${workspaceId}/integrations/workflows`);
}

export function createWorkflow(workspaceId: string, payload: Partial<AutomationWorkflow>) {
  return apiRequest<AutomationWorkflow>(`/workspaces/${workspaceId}/integrations/workflows`, {
    method: "POST",
    body: payload,
  });
}

export function runWorkflow(workspaceId: string, workflowId: string) {
  return apiRequest<AutomationExecution>(`/workspaces/${workspaceId}/integrations/workflows/${workflowId}/run`, {
    method: "POST",
  });
}

export function deleteWorkflow(workspaceId: string, workflowId: string) {
  return apiRequest<void>(`/workspaces/${workspaceId}/integrations/workflows/${workflowId}`, {
    method: "DELETE",
  });
}

export function listWorkflowExecutions(workspaceId: string, workflowId: string) {
  return apiRequest<AutomationExecution[]>(`/workspaces/${workspaceId}/integrations/workflows/${workflowId}/executions`);
}

// Scheduler
export function listScheduledJobs(workspaceId: string) {
  return apiRequest<ScheduledJob[]>(`/workspaces/${workspaceId}/integrations/scheduler/jobs`);
}

export function createScheduledJob(workspaceId: string, payload: { name: string; job_type: string; schedule: string; config: Record<string, any> }) {
  return apiRequest<ScheduledJob>(`/workspaces/${workspaceId}/integrations/scheduler/jobs`, {
    method: "POST",
    body: payload,
  });
}

export function deleteScheduledJob(workspaceId: string, jobId: string) {
  return apiRequest<void>(`/workspaces/${workspaceId}/integrations/scheduler/jobs/${jobId}`, {
    method: "DELETE",
  });
}

// MCP Servers
export function listMCPServers(workspaceId: string) {
  return apiRequest<MCPServerRegistration[]>(`/workspaces/${workspaceId}/integrations/mcp-servers`);
}

export function registerMCPServer(workspaceId: string, payload: { name: string; server_url: string; transport: string; auth_config: Record<string, any> }) {
  return apiRequest<MCPServerRegistration>(`/workspaces/${workspaceId}/integrations/mcp-servers`, {
    method: "POST",
    body: payload,
  });
}

export function deleteMCPServer(workspaceId: string, serverId: string) {
  return apiRequest<void>(`/workspaces/${workspaceId}/integrations/mcp-servers/${serverId}`, {
    method: "DELETE",
  });
}

// Real-Time Events Log
export function listIntegrationEvents(workspaceId: string) {
  return apiRequest<IntegrationEvent[]>(`/workspaces/${workspaceId}/integrations/events`);
}
