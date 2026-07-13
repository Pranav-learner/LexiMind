import { useCollaboration } from "../../context/CollaborationContext";
import { useAuth } from "../../context/AuthContext";

export default function PresenceIndicator() {
  const { user } = useAuth();
  const { onlineMembers, userStatus, setUserStatus } = useCollaboration();

  const getStatusColor = (status: string) => {
    switch (status) {
      case "online":
        return "#10B981"; // green
      case "away":
        return "#F59E0B"; // orange
      case "busy":
        return "#EF4444"; // red
      case "offline":
      default:
        return "#6B7280"; // grey
    }
  };

  return (
    <div className="presence-indicator-panel">
      <div className="presence-header">
        <div className="presence-title-area">
          <span className="presence-pulse-dot" />
          <h3>Who's Online ({onlineMembers.length})</h3>
        </div>

        {/* Change Own Status */}
        <div className="own-status-selector">
          <label>Status:</label>
          <select
            value={userStatus}
            onChange={(e) => setUserStatus(e.target.value as any)}
            style={{ borderColor: getStatusColor(userStatus) }}
          >
            <option value="online">🟢 Online</option>
            <option value="away">🟡 Away</option>
            <option value="busy">🔴 Do Not Disturb</option>
            <option value="offline">⚪ Offline</option>
          </select>
        </div>
      </div>

      <div className="online-users-list">
        {onlineMembers.length === 0 ? (
          <div className="presence-empty">Nobody online in this workspace.</div>
        ) : (
          onlineMembers.map((member) => {
            const isSelf = member.user_id === user?.id;
            return (
              <div key={member.user_id} className="online-user-row">
                <div className="avatar-wrapper">
                  <div className="user-avatar">
                    {member.display_name ? member.display_name.substring(0, 2).toUpperCase() : "??"}
                  </div>
                  <span
                    className="status-dot"
                    style={{ backgroundColor: getStatusColor(member.status) }}
                  />
                </div>

                <div className="user-details">
                  <div className="user-name">
                    {member.display_name || `User: ${member.user_id}`}
                    {isSelf && <span className="self-tag">(You)</span>}
                  </div>
                  {member.active_artifact_type && member.active_artifact_id && (
                    <div className="user-active-task">
                      👀 Viewing {member.active_artifact_type}:{" "}
                      <span className="artifact-id-text">{member.active_artifact_id}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
