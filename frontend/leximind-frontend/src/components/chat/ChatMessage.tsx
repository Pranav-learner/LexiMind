// A single chat message bubble. Memoized so streaming a new assistant turn doesn't re-render the
// entire history. Assistant content is rendered as GitHub-flavoured Markdown (code blocks with
// syntax highlighting, tables, lists); user content is rendered as plain text. Below an assistant
// message we render its citation cards. Per-message actions: Copy (all), Regenerate (assistant),
// Edit + Retry (user).

import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { ChatCitation, ChatMessage as ChatMessageType } from "../../types";
import CitationCard from "./CitationCard";

interface Props {
  message: ChatMessageType;
  streaming?: boolean; // true while this assistant bubble is being filled by token events
  onCopy: (text: string) => void;
  onRegenerate?: () => void;
  onEdit?: (message: ChatMessageType, next: string) => void;
  onRetry?: (message: ChatMessageType) => void;
  onCitation: (c: ChatCitation) => void;
}

function ChatMessageBase({
  message,
  streaming,
  onCopy,
  onRegenerate,
  onEdit,
  onRetry,
  onCitation,
}: Props) {
  const isUser = message.role === "user";
  const isError = message.meta?.status === "error";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  const roleClass = isUser ? "user" : "assistant";

  function submitEdit() {
    const next = draft.trim();
    if (next && next !== message.content) onEdit?.(message, next);
    setEditing(false);
  }

  return (
    <div className={`chat-msg ${roleClass}${isError ? " error" : ""}`}>
      <div className="chat-msg-avatar" aria-hidden="true">{isUser ? "🧑" : "🤖"}</div>
      <div className="chat-msg-body">
        <div className="chat-bubble">
          {editing ? (
            <div className="chat-edit">
              <textarea
                className="chat-edit-input"
                value={draft}
                autoFocus
                rows={Math.min(8, draft.split("\n").length + 1)}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitEdit();
                  } else if (e.key === "Escape") {
                    setEditing(false);
                    setDraft(message.content);
                  }
                }}
              />
              <div className="chat-edit-actions">
                <button className="ws-btn ghost" onClick={() => { setEditing(false); setDraft(message.content); }}>
                  Cancel
                </button>
                <button className="ws-btn primary" onClick={submitEdit}>Send</button>
              </div>
            </div>
          ) : isUser ? (
            <div className="chat-text">{message.content}</div>
          ) : (
            <div className="chat-markdown">
              {message.content ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {message.content}
                </ReactMarkdown>
              ) : streaming ? null : (
                <span className="chat-empty-answer">(no content)</span>
              )}
              {streaming && <span className="chat-cursor" aria-hidden="true" />}
            </div>
          )}
        </div>

        {isError && (
          <div className="chat-msg-error-note">
            ⚠️ This message failed to send.
          </div>
        )}

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="chat-citations">
            {message.citations.map((c, i) => (
              <CitationCard key={c.id || i} citation={c} index={i} onClick={onCitation} />
            ))}
          </div>
        )}

        {!editing && !streaming && (
          <div className="chat-msg-actions">
            <button className="chat-act" title="Copy" aria-label="Copy message" onClick={() => onCopy(message.content)}>
              📋 Copy
            </button>
            {isUser && onEdit && (
              <button className="chat-act" title="Edit and resend" aria-label="Edit message" onClick={() => { setDraft(message.content); setEditing(true); }}>
                ✏️ Edit
              </button>
            )}
            {isUser && isError && onRetry && (
              <button className="chat-act" title="Retry" aria-label="Retry message" onClick={() => onRetry(message)}>
                🔁 Retry
              </button>
            )}
            {!isUser && onRegenerate && (
              <button className="chat-act" title="Regenerate response" aria-label="Regenerate response" onClick={onRegenerate}>
                🔄 Regenerate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(ChatMessageBase);
