// Persistent AI Chat Workspace page (Phase 3, Module 4).
// Routes: /workspace/:workspaceId/chat and /workspace/:workspaceId/chat/:conversationId.
// Layout: [ConversationSidebar | ChatWindow]. ChatWindow = header (title + inline rename +
// model/temperature indicator) + a lazily-paginated message list (infinite scroll upward) +
// ChatComposer + a typing indicator while streaming. Citation clicks resolve the vector document
// id and navigate to the PDF viewer with the citation in router state.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as chatApi from "../api/chat";
import * as notesApi from "../api/notes";
import { getDocumentByVector } from "../api/viewer";
import ConversationSidebar from "../components/chat/ConversationSidebar";
import ChatMessage from "../components/chat/ChatMessage";
import ChatComposer from "../components/chat/ChatComposer";
import { useChat } from "../components/chat/useChat";
import type { ChatCitation, ChatMessage as ChatMessageType, Conversation } from "../types";

export default function ChatWorkspace() {
  const { workspaceId = "", conversationId } = useParams();
  const navigate = useNavigate();
  const [reloadSignal, setReloadSignal] = useState(0);
  const [creating, setCreating] = useState(false);

  const bumpSidebar = useCallback(() => setReloadSignal((n) => n + 1), []);

  const newChat = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const conv = await chatApi.createConversation(workspaceId, {});
      bumpSidebar();
      navigate(`/workspace/${workspaceId}/chat/${conv.id}`);
    } catch {
      // ignore; sidebar shows any subsequent errors
    } finally {
      setCreating(false);
    }
  }, [creating, workspaceId, bumpSidebar, navigate]);

  const selectConversation = useCallback(
    (id: string) => navigate(`/workspace/${workspaceId}/chat/${id}`),
    [navigate, workspaceId],
  );

  const onCitation = useCallback(
    async (c: ChatCitation) => {
      try {
        const doc = await getDocumentByVector(workspaceId, c.document_id);
        navigate(`/workspace/${workspaceId}/document/${doc.id}`, {
          state: { citation: { page: c.page_number, text: c.citation_text } },
        });
      } catch {
        // best-effort; leave the user in the chat
      }
    },
    [navigate, workspaceId],
  );

  return (
    <div className="chat-page">
      <ConversationSidebar
        ws={workspaceId}
        activeId={conversationId ?? null}
        reloadSignal={reloadSignal}
        onSelect={selectConversation}
        onNew={newChat}
      />
      {conversationId ? (
        <ChatWindow
          key={conversationId}
          ws={workspaceId}
          conversationId={conversationId}
          onCitation={onCitation}
          onActivity={bumpSidebar}
        />
      ) : (
        <div className="chat-window chat-empty-state">
          <div className="ws-empty">
            <div className="ws-empty-mark">💬</div>
            <h3>Your AI chat workspace</h3>
            <p>Start a new conversation or pick one from the sidebar. Answers cite your documents.</p>
            <button className="ws-btn primary" onClick={newChat} disabled={creating}>
              ✚ New chat
            </button>
            <div style={{ marginTop: 16 }}>
              <Link className="ws-link" to={`/workspace/${workspaceId}`}>← Back to workspace</Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface WindowProps {
  ws: string;
  conversationId: string;
  onCitation: (c: ChatCitation) => void;
  onActivity: () => void;
}

function ChatWindow({ ws, conversationId, onCitation, onActivity }: WindowProps) {
  const navigate = useNavigate();
  const [conv, setConv] = useState<Conversation | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);

  const {
    messages,
    streaming,
    streamingId,
    error,
    loadingHistory,
    loadingOlder,
    hasMore,
    send,
    cancel,
    regenerate,
    editMessage,
    retry,
    loadOlder,
  } = useChat(ws, conversationId);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickBottomRef = useRef(true);
  const prevHeightRef = useRef(0);
  const prevStreamingRef = useRef(false);

  // Module 6: persist an assistant answer (with its citations) as an editable Note, then open it.
  const saveAsNote = useCallback(
    async (m: ChatMessageType) => {
      try {
        const note = await notesApi.noteFromMessage(ws, m.id);
        navigate(`/workspace/${ws}/notes/${note.id}`);
      } catch {
        /* best-effort; stay in chat */
      }
    },
    [ws, navigate],
  );

  // Load the conversation metadata for the header.
  const loadConv = useCallback(() => {
    let alive = true;
    chatApi
      .getConversation(ws, conversationId)
      .then((c) => alive && setConv(c))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [ws, conversationId]);
  useEffect(() => loadConv(), [loadConv]);

  // Refresh the sidebar + header once a streamed reply finishes.
  useEffect(() => {
    if (prevStreamingRef.current && !streaming) {
      onActivity();
      loadConv();
    }
    prevStreamingRef.current = streaming;
  }, [streaming, onActivity, loadConv]);

  // Track whether the user is pinned to the bottom (so we can auto-scroll on new content).
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (el.scrollTop < 60 && hasMore && !loadingOlder) {
      prevHeightRef.current = el.scrollHeight;
      loadOlder();
    }
  }, [hasMore, loadingOlder, loadOlder]);

  // Keep scroll anchored to the bottom on new content; restore position after prepending older.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (prevHeightRef.current) {
      el.scrollTop = el.scrollHeight - prevHeightRef.current;
      prevHeightRef.current = 0;
      return;
    }
    if (stickBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function submitTitle() {
    const next = titleDraft.trim();
    setEditingTitle(false);
    if (conv && next && next !== conv.title) {
      chatApi
        .updateConversation(ws, conversationId, { title: next })
        .then((c) => {
          setConv(c);
          onActivity();
        })
        .catch(() => {});
    }
  }

  const title = conv?.title || "New chat";
  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  return (
    <div className="chat-window">
      <header className="chat-window-header">
        <button
          className="ws-icon-btn"
          title="Back to workspace"
          aria-label="Back to workspace"
          onClick={() => navigate(`/workspace/${ws}`)}
        >
          ←
        </button>
        <div className="chat-window-title">
          {editingTitle ? (
            <input
              className="chat-title-input"
              value={titleDraft}
              autoFocus
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={submitTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitTitle();
                else if (e.key === "Escape") setEditingTitle(false);
              }}
              aria-label="Conversation title"
            />
          ) : (
            <button
              className="chat-title-btn"
              title="Rename conversation"
              onClick={() => {
                setTitleDraft(title);
                setEditingTitle(true);
              }}
            >
              {title} <span className="chat-title-edit" aria-hidden="true">✏️</span>
            </button>
          )}
        </div>
        {conv && (
          <div className="chat-window-indicators">
            <span className="chat-indicator" title="Model">{conv.model_name || "model"}</span>
            <span className="chat-indicator" title="Temperature">🌡 {conv.temperature.toFixed(1)}</span>
          </div>
        )}
      </header>

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-messages">
          {loadingOlder && <div className="chat-loading-older">Loading earlier messages…</div>}
          {loadingHistory && messages.length === 0 ? (
            <div className="chat-window-status">
              <span className="ws-brand-mark spin">🧠</span>
              <p>Loading conversation…</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="chat-window-status">
              <div className="ws-empty-mark">👋</div>
              <p>Ask your first question to get started.</p>
            </div>
          ) : (
            messages.map((m) => (
              <ChatMessage
                key={m.id}
                message={m}
                streaming={streaming && m.id === streamingId}
                onCopy={(t) => navigator.clipboard?.writeText(t)}
                onCitation={onCitation}
                onRegenerate={
                  !streaming && m.id === lastAssistantId && m.role === "assistant"
                    ? () => regenerate(m)
                    : undefined
                }
                onEdit={m.role === "user" && !streaming ? editMessage : undefined}
                onRetry={m.role === "user" ? retry : undefined}
                onSaveAsNote={m.role === "assistant" ? saveAsNote : undefined}
              />
            ))
          )}
          {streaming && (
            <div className="chat-typing" aria-live="polite">
              <span className="chat-typing-dot" />
              <span className="chat-typing-dot" />
              <span className="chat-typing-dot" />
            </div>
          )}
        </div>
      </div>

      {error && <div className="ws-error-banner chat-window-error">{error}</div>}

      <ChatComposer onSend={send} onStop={cancel} streaming={streaming} />
    </div>
  );
}
