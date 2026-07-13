import { useEffect, useState } from "react";
import * as api from "../../api/collaboration";
import type { WorkspaceMember, Invitation } from "../../types";
import { ApiError } from "../../api/client";

interface Props {
  workspaceId: string;
  workspaceName: string;
  onClose: () => void;
  onOwnershipTransferred?: () => void;
}

export default function WorkspaceShareModal({
  workspaceId,
  workspaceName,
  onClose,
  onOwnershipTransferred,
}: Props) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [addUserId, setAddUserId] = useState("");
  const [addUserRole, setAddUserRole] = useState("viewer");

  const [cloneName, setCloneName] = useState(`${workspaceName} (Copy)`);
  const [cloneDesc, setCloneDesc] = useState("");
  const [showCloneForm, setShowCloneForm] = useState(false);

  const [newOwnerId, setNewOwnerId] = useState("");
  const [showTransferForm, setShowTransferForm] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadData = async () => {
    try {
      const mems = await api.listWorkspaceMembers(workspaceId);
      setMembers(mems);
      const invs = await api.listWorkspaceInvitations(workspaceId);
      setInvitations(invs);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadData();
  }, [workspaceId]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!inviteEmail.trim()) return;
    try {
      await api.inviteToWorkspace(workspaceId, inviteEmail.trim(), inviteRole);
      setInviteEmail("");
      setSuccess(`Invitation sent to ${inviteEmail}`);
      loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to invite email");
    }
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!addUserId.trim()) return;
    try {
      await api.addWorkspaceMember(workspaceId, addUserId.trim(), addUserRole);
      setAddUserId("");
      setSuccess(`User ${addUserId} added directly to workspace`);
      loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add user");
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    setError(null);
    setSuccess(null);
    try {
      await api.updateWorkspaceMemberRole(workspaceId, userId, role);
      setSuccess("Role updated successfully");
      loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update role");
    }
  };

  const handleRemove = async (userId: string) => {
    if (!window.confirm("Remove user from this workspace?")) return;
    setError(null);
    setSuccess(null);
    try {
      await api.removeWorkspaceMember(workspaceId, userId);
      setSuccess("User removed");
      loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove member");
    }
  };

  const handleClone = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    try {
      const cloned = await api.cloneWorkspace(workspaceId, cloneName, cloneDesc);
      setSuccess(`Workspace successfully cloned as "${cloned.name}"`);
      setShowCloneForm(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to clone workspace");
    }
  };

  const handleTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!window.confirm("WARNING: Transferring ownership will remove your owner status and grant it to the new user. You will become a member. Proceed?")) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      await api.transferWorkspaceOwnership(workspaceId, newOwnerId);
      setSuccess("Ownership transferred successfully!");
      setShowTransferForm(false);
      if (onOwnershipTransferred) onOwnershipTransferred();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to transfer ownership");
    }
  };

  return (
    <div className="collab-modal-overlay">
      <div className="collab-modal x-large">
        <div className="collab-modal-header">
          <h2>Share Workspace: {workspaceName}</h2>
          <button className="collab-close-btn" onClick={onClose}>×</button>
        </div>

        <div className="collab-modal-body split">
          {/* LEFT PANELS: Invite, Add, Settings */}
          <div className="collab-col">
            {error && <div className="collab-error-banner">{error}</div>}
            {success && <div className="collab-success-banner">{success}</div>}

            <div className="collab-form-section">
              <h3>Invite Member by Email</h3>
              <form onSubmit={handleInvite} className="collab-inline-form">
                <input
                  type="email"
                  required
                  placeholder="name@example.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                />
                <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="admin">Admin</option>
                </select>
                <button type="submit" className="ws-btn primary">Invite</button>
              </form>
            </div>

            <div className="collab-form-section" style={{ marginTop: 20 }}>
              <h3>Add Member directly by ID</h3>
              <form onSubmit={handleAddMember} className="collab-inline-form">
                <input
                  type="text"
                  required
                  placeholder="user_abcdef123"
                  value={addUserId}
                  onChange={(e) => setAddUserId(e.target.value)}
                />
                <select value={addUserRole} onChange={(e) => setAddUserRole(e.target.value)}>
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="admin">Admin</option>
                </select>
                <button type="submit" className="ws-btn primary">Add</button>
              </form>
            </div>

            <div className="collab-form-section" style={{ marginTop: 30, borderTop: "1px solid var(--border)", paddingTop: 20 }}>
              <h3>Workspace Operations</h3>
              <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                <button className="ws-btn ghost" onClick={() => { setShowCloneForm(!showCloneForm); setShowTransferForm(false); }}>
                  📋 Clone Workspace
                </button>
                <button className="ws-btn ghost danger" onClick={() => { setShowTransferForm(!showTransferForm); setShowCloneForm(false); }}>
                  ⚠️ Transfer Ownership
                </button>
              </div>

              {showCloneForm && (
                <form onSubmit={handleClone} className="operations-subform">
                  <h4>Clone Workspace</h4>
                  <div className="form-group">
                    <label>New Name</label>
                    <input
                      type="text"
                      required
                      value={cloneName}
                      onChange={(e) => setCloneName(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label>Description</label>
                    <textarea
                      value={cloneDesc}
                      onChange={(e) => setCloneDesc(e.target.value)}
                      placeholder="Optional description"
                    />
                  </div>
                  <button type="submit" className="ws-btn primary">Confirm Clone</button>
                </form>
              )}

              {showTransferForm && (
                <form onSubmit={handleTransfer} className="operations-subform">
                  <h4>Transfer Ownership</h4>
                  <div className="form-group">
                    <label>New Owner User ID</label>
                    <input
                      type="text"
                      required
                      placeholder="user_abcdef123"
                      value={newOwnerId}
                      onChange={(e) => setNewOwnerId(e.target.value)}
                    />
                  </div>
                  <button type="submit" className="ws-btn primary danger">Transfer Now</button>
                </form>
              )}
            </div>
          </div>

          {/* RIGHT PANELS: Members List, Active Invites */}
          <div className="collab-col border-left">
            <h3>Workspace Members ({members.length})</h3>
            <div className="members-list" style={{ maxHeight: 200, overflowY: "auto", marginBottom: 20 }}>
              {members.map((member) => (
                <div key={member.id} className="member-item">
                  <div className="member-info">
                    <div className="member-name">User: {member.user_id}</div>
                    <div className="member-joined">Joined: {new Date(member.joined_at).toLocaleDateString()}</div>
                  </div>
                  <div className="member-actions">
                    <select
                      value={member.role}
                      onChange={(e) => handleRoleChange(member.user_id, e.target.value)}
                    >
                      <option value="viewer">Viewer</option>
                      <option value="editor">Editor</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button className="member-remove-btn" onClick={() => handleRemove(member.user_id)}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <h3>Pending Invitations ({invitations.filter((i) => i.status === "pending").length})</h3>
            <div className="members-list" style={{ maxHeight: 150, overflowY: "auto" }}>
              {invitations.map((inv) => (
                <div key={inv.id} className="member-item">
                  <div className="member-info">
                    <div className="member-name">{inv.invitee_email}</div>
                    <div className="member-joined">Role: {inv.role} | Status: <span className={`status-${inv.status}`}>{inv.status}</span></div>
                  </div>
                  <div className="member-actions">
                    <span className="invitation-token-label">Token: {inv.token.substring(0, 8)}...</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
