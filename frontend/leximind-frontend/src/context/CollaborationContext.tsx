import React, { createContext, useContext, useEffect, useState, useRef, useMemo } from "react";
import * as api from "../api/collaboration";
import type { PresenceMember, ActivityEvent } from "../types";

interface CollaborationContextValue {
  workspaceId: string;
  onlineMembers: PresenceMember[];
  recentActivity: ActivityEvent[];
  commentsTrigger: number;
  triggerCommentsReload: () => void;
  activeArtifact: { type: string | null; id: string | null };
  setActiveArtifact: (type: string | null, id: string | null) => void;
  userStatus: "online" | "away" | "busy" | "offline";
  setUserStatus: (status: "online" | "away" | "busy" | "offline") => void;
}

const CollaborationContext = createContext<CollaborationContextValue | null>(null);

export function CollaborationProvider({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: React.ReactNode;
}) {
  const [onlineMembers, setOnlineMembers] = useState<PresenceMember[]>([]);
  const [recentActivity, setRecentActivity] = useState<ActivityEvent[]>([]);
  const [commentsTrigger, setCommentsTrigger] = useState(0);
  const [activeArtifact, setActiveArtifactState] = useState<{ type: string | null; id: string | null }>({
    type: null,
    id: null,
  });
  const [userStatus, setUserStatus] = useState<"online" | "away" | "busy" | "offline">("online");

  const activeArtifactRef = useRef(activeArtifact);
  const userStatusRef = useRef(userStatus);
  activeArtifactRef.current = activeArtifact;
  userStatusRef.current = userStatus;

  const setActiveArtifact = (type: string | null, id: string | null) => {
    setActiveArtifactState({ type, id });
  };

  const triggerCommentsReload = () => {
    setCommentsTrigger((prev) => prev + 1);
  };

  // Heartbeat loop
  useEffect(() => {
    if (!workspaceId) return;

    const runHeartbeat = async () => {
      try {
        await api.sendHeartbeat(workspaceId, {
          active_document_id: activeArtifactRef.current.type === "document" ? activeArtifactRef.current.id : null,
          active_artifact_type: activeArtifactRef.current.type,
          active_artifact_id: activeArtifactRef.current.id,
          status: userStatusRef.current,
        });
        const presence = await api.listOnlinePresence(workspaceId);
        setOnlineMembers(presence.members);
      } catch (err) {
        console.error("Presence heartbeat failed:", err);
      }
    };

    // Run immediately then every 5 seconds
    runHeartbeat();
    const interval = setInterval(runHeartbeat, 5000);

    return () => clearInterval(interval);
  }, [workspaceId]);

  // Sync / Long Polling loop
  useEffect(() => {
    if (!workspaceId) return;

    let active = true;
    let cursor = 0;
    let abortController = new AbortController();

    const startPoll = async () => {
      while (active) {
        try {
          const res = await api.pollSyncEvents(workspaceId, cursor, 30, abortController.signal);
          if (!active) break;
          cursor = res.cursor;
          if (res.events && res.events.length > 0) {
            let shouldReloadComments = false;
            let shouldReloadPresence = false;
            let shouldReloadActivity = false;

            res.events.forEach((evt) => {
              if (evt.event_type === "comment") {
                shouldReloadComments = true;
              } else if (evt.event_type === "presence") {
                shouldReloadPresence = true;
              } else if (evt.event_type === "activity" || evt.event_type === "member_added" || evt.event_type === "member_removed") {
                shouldReloadActivity = true;
              }
            });

            if (shouldReloadComments) {
              setCommentsTrigger((prev) => prev + 1);
            }
            if (shouldReloadPresence) {
              api.listOnlinePresence(workspaceId).then((p) => {
                if (active) setOnlineMembers(p.members);
              });
            }
            if (shouldReloadActivity) {
              api.listWorkspaceActivity(workspaceId, 10).then((act) => {
                if (active) setRecentActivity(act);
              });
            }
          }
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") {
            // normal abort
          } else {
            console.error("Sync poll error:", err);
            // wait a little bit before retrying on error
            await new Promise((resolve) => setTimeout(resolve, 2000));
          }
        }
      }
    };

    startPoll();

    // Fetch initial activity list
    api.listWorkspaceActivity(workspaceId, 10).then((act) => {
      if (active) setRecentActivity(act);
    });

    return () => {
      active = false;
      abortController.abort();
    };
  }, [workspaceId]);

  const value = useMemo(
    () => ({
      workspaceId,
      onlineMembers,
      recentActivity,
      commentsTrigger,
      triggerCommentsReload,
      activeArtifact,
      setActiveArtifact,
      userStatus,
      setUserStatus,
    }),
    [workspaceId, onlineMembers, recentActivity, commentsTrigger, activeArtifact, userStatus]
  );

  return <CollaborationContext.Provider value={value}>{children}</CollaborationContext.Provider>;
}

export function useCollaboration() {
  const ctx = useContext(CollaborationContext);
  if (!ctx) throw new Error("useCollaboration must be used within a CollaborationProvider");
  return ctx;
}
