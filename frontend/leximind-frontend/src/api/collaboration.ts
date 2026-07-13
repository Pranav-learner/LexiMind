import { apiRequest } from "./client";
import type {
  Organization,
  OrganizationMember,
  WorkspaceMember,
  Invitation,
  Comment,
  ActivityEvent,
  VersionSnapshot,
  WorkspacePresenceResponse,
  SyncPollResponse,
  Workspace,
} from "../types";

// ════════════════════════════════════════════════════════════════════════
//  1. Organizations
// ════════════════════════════════════════════════════════════════════════

export function createOrganization(name: string, description = "") {
  return apiRequest<Organization>("/collaboration/organizations", {
    method: "POST",
    body: { name, description },
  });
}

export function listOrganizations() {
  return apiRequest<Organization[]>("/collaboration/organizations");
}

export function getOrganization(id: string) {
  return apiRequest<Organization>(`/collaboration/organizations/${id}`);
}

export function updateOrganization(id: string, name: string, description?: string) {
  return apiRequest<Organization>(`/collaboration/organizations/${id}`, {
    method: "PATCH",
    body: { name, description },
  });
}

export function deleteOrganization(id: string) {
  return apiRequest<void>(`/collaboration/organizations/${id}`, {
    method: "DELETE",
  });
}

export function addOrganizationMember(orgId: string, userId: string, role = "member") {
  return apiRequest<OrganizationMember>(`/collaboration/organizations/${orgId}/members`, {
    method: "POST",
    body: { user_id: userId, role },
  });
}

export function listOrganizationMembers(orgId: string) {
  return apiRequest<OrganizationMember[]>(`/collaboration/organizations/${orgId}/members`);
}

export function changeOrganizationMemberRole(orgId: string, userId: string, role: string) {
  return apiRequest<OrganizationMember>(`/collaboration/organizations/${orgId}/members/${userId}`, {
    method: "PATCH",
    body: { role },
  });
}

export function removeOrganizationMember(orgId: string, userId: string) {
  return apiRequest<void>(`/collaboration/organizations/${orgId}/members/${userId}`, {
    method: "DELETE",
  });
}

// ════════════════════════════════════════════════════════════════════════
//  2. Workspace Sharing & Invitations
// ════════════════════════════════════════════════════════════════════════

export function getWorkspaceAccess(workspaceId: string) {
  return apiRequest<{ has_access: boolean; role: string | null }>(
    `/collaboration/workspaces/${workspaceId}/access`
  );
}

export function listWorkspaceMembers(workspaceId: string) {
  return apiRequest<WorkspaceMember[]>(`/collaboration/workspaces/${workspaceId}/members`);
}

export function addWorkspaceMember(workspaceId: string, userId: string, role = "viewer") {
  return apiRequest<WorkspaceMember>(`/collaboration/workspaces/${workspaceId}/members`, {
    method: "POST",
    body: { user_id: userId, role },
  });
}

export function updateWorkspaceMemberRole(workspaceId: string, userId: string, role: string) {
  return apiRequest<WorkspaceMember>(`/collaboration/workspaces/${workspaceId}/members/${userId}`, {
    method: "PATCH",
    body: { role },
  });
}

export function removeWorkspaceMember(workspaceId: string, userId: string) {
  return apiRequest<void>(`/collaboration/workspaces/${workspaceId}/members/${userId}`, {
    method: "DELETE",
  });
}

export function inviteToWorkspace(workspaceId: string, email: string, role = "viewer") {
  return apiRequest<Invitation>(`/collaboration/workspaces/${workspaceId}/invitations`, {
    method: "POST",
    body: { email, role },
  });
}

export function listWorkspaceInvitations(workspaceId: string) {
  return apiRequest<Invitation[]>(`/collaboration/workspaces/${workspaceId}/invitations`);
}

export function acceptInvitation(token: string) {
  return apiRequest<Invitation>(`/collaboration/invitations/${token}/accept`, {
    method: "POST",
  });
}

export function declineInvitation(token: string) {
  return apiRequest<Invitation>(`/collaboration/invitations/${token}/decline`, {
    method: "POST",
  });
}

// ════════════════════════════════════════════════════════════════════════
//  3. Unified Commenting
// ════════════════════════════════════════════════════════════════════════

export function listComments(workspaceId: string, targetType: string, targetId: string) {
  return apiRequest<Comment[]>(
    `/collaboration/workspaces/${workspaceId}/comments?target_type=${targetType}&target_id=${targetId}`
  );
}

export function createComment(
  workspaceId: string,
  targetType: string,
  targetId: string,
  content: string,
  parentCommentId: string | null = null
) {
  return apiRequest<Comment>(`/collaboration/workspaces/${workspaceId}/comments`, {
    method: "POST",
    body: {
      target_type: targetType,
      target_id: targetId,
      content,
      parent_comment_id: parentCommentId,
    },
  });
}

export function editComment(commentId: string, content: string) {
  return apiRequest<Comment>(`/collaboration/collaboration/comments/${commentId}`, {
    method: "PATCH",
    body: { content },
  });
}

export function resolveComment(commentId: string) {
  return apiRequest<Comment>(`/collaboration/collaboration/comments/${commentId}/resolve`, {
    method: "POST",
  });
}

export function deleteComment(commentId: string) {
  return apiRequest<void>(`/collaboration/collaboration/comments/${commentId}`, {
    method: "DELETE",
  });
}

// ════════════════════════════════════════════════════════════════════════
//  4. Activity Feed & Version snapshots
// ════════════════════════════════════════════════════════════════════════

export function listWorkspaceActivity(workspaceId: string, limit = 50, offset = 0) {
  return apiRequest<ActivityEvent[]>(
    `/collaboration/workspaces/${workspaceId}/activity?limit=${limit}&offset=${offset}`
  );
}

export function listVersionSnapshots(workspaceId: string, targetType?: string, targetId?: string) {
  const q = targetType && targetId ? `?target_type=${targetType}&target_id=${targetId}` : "";
  return apiRequest<VersionSnapshot[]>(`/collaboration/workspaces/${workspaceId}/versions${q}`);
}

// ════════════════════════════════════════════════════════════════════════
//  5. Presence heartbeats & online listing
// ════════════════════════════════════════════════════════════════════════

export function sendHeartbeat(
  workspaceId: string,
  payload: {
    active_document_id?: string | null;
    active_artifact_type?: string | null;
    active_artifact_id?: string | null;
    status?: "online" | "away" | "busy" | "offline";
  }
) {
  return apiRequest<void>(`/collaboration/workspaces/${workspaceId}/presence/heartbeat`, {
    method: "POST",
    body: payload,
  });
}

export function listOnlinePresence(workspaceId: string) {
  return apiRequest<WorkspacePresenceResponse>(`/collaboration/workspaces/${workspaceId}/presence`);
}

// ════════════════════════════════════════════════════════════════════════
//  6. Sync (Long polling loop)
// ════════════════════════════════════════════════════════════════════════

export function pollSyncEvents(workspaceId: string, cursor: number, timeout = 30, signal?: AbortSignal) {
  return apiRequest<SyncPollResponse>(
    `/collaboration/workspaces/${workspaceId}/sync?cursor=${cursor}&timeout=${timeout}`,
    { signal }
  );
}

// ════════════════════════════════════════════════════════════════════════
//  7. Workspace Clone & Ownership Transfer
// ════════════════════════════════════════════════════════════════════════

export function cloneWorkspace(workspaceId: string, name: string, description = "") {
  return apiRequest<Workspace>(`/collaboration/workspaces/${workspaceId}/clone`, {
    method: "POST",
    body: { name, description },
  });
}

export function transferWorkspaceOwnership(workspaceId: string, newOwnerId: string) {
  return apiRequest<Workspace>(`/collaboration/workspaces/${workspaceId}/transfer`, {
    method: "POST",
    body: { new_owner_id: newOwnerId },
  });
}
