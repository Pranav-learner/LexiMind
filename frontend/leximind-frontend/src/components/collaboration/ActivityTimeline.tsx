import { useEffect, useState } from "react";
import type { ActivityEvent } from "../../types";
import { useCollaboration } from "../../context/CollaborationContext";

export default function ActivityTimeline() {
  const { recentActivity } = useCollaboration();
  const [filterType, setFilterType] = useState<string>("all");
  const [activities, setActivities] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    if (recentActivity) {
      setActivities(recentActivity);
    }
  }, [recentActivity]);

  const getEventIcon = (type: string) => {
    switch (type) {
      case "member_added":
        return "👤➕";
      case "member_removed":
        return "👤➖";
      case "comment_created":
      case "comment":
        return "💬";
      case "document_uploaded":
      case "document":
        return "📄";
      case "workspace_created":
      case "workspace_updated":
        return "🗂️";
      default:
        return "🔔";
    }
  };

  const filtered = activities.filter((act) => {
    if (filterType === "all") return true;
    if (filterType === "comments") return act.event_type.includes("comment");
    if (filterType === "documents") return act.event_type.includes("document");
    if (filterType === "members") return act.event_type.includes("member");
    return true;
  });

  return (
    <div className="activity-timeline-container">
      <div className="activity-timeline-header">
        <h3>⚡ Workspace Activity Feed</h3>
        <select
          className="timeline-filter"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
        >
          <option value="all">All Events</option>
          <option value="comments">Comments</option>
          <option value="documents">Documents</option>
          <option value="members">Members</option>
        </select>
      </div>

      <div className="timeline-list">
        {filtered.length === 0 ? (
          <div className="timeline-empty">No matching events in the activity feed.</div>
        ) : (
          filtered.map((act) => (
            <div key={act.id} className="timeline-item">
              <div className="timeline-icon">{getEventIcon(act.event_type)}</div>
              <div className="timeline-content">
                <div className="timeline-desc">{act.description}</div>
                <div className="timeline-meta">
                  <span className="timeline-actor">By User: {act.actor_id}</span>
                  <span className="timeline-divider">•</span>
                  <span className="timeline-time">{new Date(act.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
