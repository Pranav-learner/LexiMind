import { useEffect, useState, useRef } from "react";
import * as api from "../../api/collaboration";
import type { Organization, OrganizationMember } from "../../types";
import { ApiError } from "../../api/client";

export default function OrganizationSwitcher() {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [currentOrg, setCurrentOrg] = useState<Organization | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showManageModal, setShowManageModal] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgDesc, setNewOrgDesc] = useState("");
  const [inviteUserId, setInviteUserId] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [modalError, setModalError] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  const loadOrgs = async () => {
    try {
      const data = await api.listOrganizations();
      setOrgs(data);
      if (data.length > 0 && !currentOrg) {
        setCurrentOrg(data[0]);
      }
    } catch (err) {
      console.error("Failed to load organizations", err);
    }
  };

  useEffect(() => {
    loadOrgs();
  }, []);

  useEffect(() => {
    if (currentOrg) {
      api.listOrganizationMembers(currentOrg.id)
        .then(setMembers)
        .catch(console.error);
    } else {
      setMembers([]);
    }
  }, [currentOrg]);

  // Click outside to close dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError(null);
    if (!newOrgName.trim()) return;
    try {
      const created = await api.createOrganization(newOrgName, newOrgDesc);
      setNewOrgName("");
      setNewOrgDesc("");
      setShowCreateModal(false);
      setCurrentOrg(created);
      await loadOrgs();
    } catch (err) {
      setModalError(err instanceof ApiError ? err.message : "Failed to create organization");
    }
  };

  const handleInviteMember = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError(null);
    if (!currentOrg || !inviteUserId.trim()) return;
    try {
      await api.addOrganizationMember(currentOrg.id, inviteUserId.trim(), inviteRole);
      setInviteUserId("");
      // Refresh members
      const updated = await api.listOrganizationMembers(currentOrg.id);
      setMembers(updated);
    } catch (err) {
      setModalError(err instanceof ApiError ? err.message : "Failed to add member");
    }
  };

  const handleRoleChange = async (memberId: string, newRole: string) => {
    if (!currentOrg) return;
    try {
      await api.changeOrganizationMemberRole(currentOrg.id, memberId, newRole);
      // Refresh members
      const updated = await api.listOrganizationMembers(currentOrg.id);
      setMembers(updated);
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to change role");
    }
  };

  const handleRemoveMember = async (memberId: string) => {
    if (!currentOrg) return;
    if (!window.confirm("Remove this member from the organization?")) return;
    try {
      await api.removeOrganizationMember(currentOrg.id, memberId);
      // Refresh members
      const updated = await api.listOrganizationMembers(currentOrg.id);
      setMembers(updated);
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to remove member");
    }
  };

  return (
    <div className="org-switcher-container" ref={containerRef}>
      <div className="org-switcher-trigger" onClick={() => setShowDropdown(!showDropdown)}>
        <span className="org-avatar">🏢</span>
        <span className="org-name">{currentOrg ? currentOrg.name : "Personal Space"}</span>
        <span className="org-caret">▼</span>
      </div>

      {showDropdown && (
        <div className="org-dropdown-menu">
          <div className="org-dropdown-section">
            <div className="org-dropdown-header">Organizations</div>
            {orgs.map((org) => (
              <div
                key={org.id}
                className={`org-dropdown-item ${currentOrg?.id === org.id ? "active" : ""}`}
                onClick={() => {
                  setCurrentOrg(org);
                  setShowDropdown(false);
                }}
              >
                <span className="org-bullet">🏢</span>
                <span>{org.name}</span>
              </div>
            ))}
            <div
              className={`org-dropdown-item ${!currentOrg ? "active" : ""}`}
              onClick={() => {
                setCurrentOrg(null);
                setShowDropdown(false);
              }}
            >
              <span className="org-bullet">👤</span>
              <span>Personal Space (No Org)</span>
            </div>
          </div>

          <div className="org-dropdown-divider" />

          <div className="org-dropdown-actions">
            {currentOrg && (
              <button
                className="org-action-btn"
                onClick={() => {
                  setShowManageModal(true);
                  setShowDropdown(false);
                  setModalError(null);
                }}
              >
                ⚙️ Manage Organization
              </button>
            )}
            <button
              className="org-action-btn"
              onClick={() => {
                setShowCreateModal(true);
                setShowDropdown(false);
                setModalError(null);
              }}
            >
              ➕ Create Organization
            </button>
          </div>
        </div>
      )}

      {/* CREATE ORG MODAL */}
      {showCreateModal && (
        <div className="collab-modal-overlay">
          <div className="collab-modal">
            <div className="collab-modal-header">
              <h2>Create Organization</h2>
              <button className="collab-close-btn" onClick={() => setShowCreateModal(false)}>×</button>
            </div>
            <form onSubmit={handleCreateOrg}>
              <div className="collab-modal-body">
                {modalError && <div className="collab-error-banner">{modalError}</div>}
                <div className="form-group">
                  <label>Organization Name</label>
                  <input
                    type="text"
                    required
                    value={newOrgName}
                    onChange={(e) => setNewOrgName(e.target.value)}
                    placeholder="e.g. Acme Corp"
                  />
                </div>
                <div className="form-group">
                  <label>Description</label>
                  <textarea
                    value={newOrgDesc}
                    onChange={(e) => setNewOrgDesc(e.target.value)}
                    placeholder="Brief description..."
                  />
                </div>
              </div>
              <div className="collab-modal-footer">
                <button type="button" className="ws-btn ghost" onClick={() => setShowCreateModal(false)}>Cancel</button>
                <button type="submit" className="ws-btn primary">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MANAGE ORG MODAL */}
      {showManageModal && currentOrg && (
        <div className="collab-modal-overlay">
          <div className="collab-modal large">
            <div className="collab-modal-header">
              <h2>Manage {currentOrg.name}</h2>
              <button className="collab-close-btn" onClick={() => setShowManageModal(false)}>×</button>
            </div>
            <div className="collab-modal-body split">
              <div className="collab-col">
                <h3>Invite Member</h3>
                {modalError && <div className="collab-error-banner">{modalError}</div>}
                <form onSubmit={handleInviteMember}>
                  <div className="form-group">
                    <label>User ID</label>
                    <input
                      type="text"
                      required
                      value={inviteUserId}
                      onChange={(e) => setInviteUserId(e.target.value)}
                      placeholder="e.g. user_abcdef123..."
                    />
                  </div>
                  <div className="form-group">
                    <label>Role</label>
                    <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                  <button type="submit" className="ws-btn primary" style={{ width: "100%", marginTop: 15 }}>
                    Add Member
                  </button>
                </form>
              </div>

              <div className="collab-col border-left">
                <h3>Members List ({members.length})</h3>
                <div className="members-list">
                  {members.map((member) => (
                    <div key={member.id} className="member-item">
                      <div className="member-info">
                        <div className="member-name">User: {member.user_id}</div>
                        <div className="member-joined">Joined: {new Date(member.joined_at).toLocaleDateString()}</div>
                      </div>
                      <div className="member-actions">
                        <select
                          value={member.role}
                          disabled={member.user_id === currentOrg.creator_id}
                          onChange={(e) => handleRoleChange(member.user_id, e.target.value)}
                        >
                          <option value="member">Member</option>
                          <option value="admin">Admin</option>
                        </select>
                        {member.user_id !== currentOrg.creator_id && (
                          <button
                            className="member-remove-btn"
                            onClick={() => handleRemoveMember(member.user_id)}
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
