import { useEffect, useState } from "react";
import * as api from "../../api/collaboration";
import type { Comment } from "../../types";
import { useCollaboration } from "../../context/CollaborationContext";
import { useAuth } from "../../context/AuthContext";
import { ApiError } from "../../api/client";

interface Props {
  targetType: string;
  targetId: string;
}

export default function CommentPanel({ targetType, targetId }: Props) {
  const { user } = useAuth();
  const { workspaceId, commentsTrigger, triggerCommentsReload } = useCollaboration();

  const [comments, setComments] = useState<Comment[]>([]);
  const [newCommentText, setNewCommentText] = useState("");
  const [replyText, setReplyText] = useState<Record<string, string>>({});
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchComments = async () => {
    if (!workspaceId || !targetId) return;
    setLoading(true);
    try {
      const data = await api.listComments(workspaceId, targetType, targetId);
      setComments(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchComments();
  }, [workspaceId, targetType, targetId, commentsTrigger]);

  const handleSubmitComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCommentText.trim() || !workspaceId) return;
    setError(null);
    try {
      await api.createComment(workspaceId, targetType, targetId, newCommentText.trim());
      setNewCommentText("");
      triggerCommentsReload();
      fetchComments();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add comment");
    }
  };

  const handleAddReply = async (parentId: string) => {
    const text = replyText[parentId];
    if (!text || !text.trim() || !workspaceId) return;
    try {
      await api.createComment(workspaceId, targetType, targetId, text.trim(), parentId);
      setReplyText((prev) => ({ ...prev, [parentId]: "" }));
      setReplyingTo(null);
      triggerCommentsReload();
      fetchComments();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to add reply");
    }
  };

  const handleEditComment = async (commentId: string) => {
    if (!editText.trim()) return;
    try {
      await api.editComment(commentId, editText.trim());
      setEditingCommentId(null);
      setEditText("");
      triggerCommentsReload();
      fetchComments();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to edit comment");
    }
  };

  const handleResolveComment = async (commentId: string) => {
    try {
      await api.resolveComment(commentId);
      triggerCommentsReload();
      fetchComments();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to resolve comment");
    }
  };

  const handleDeleteComment = async (commentId: string) => {
    if (!window.confirm("Delete this comment?")) return;
    try {
      await api.deleteComment(commentId);
      triggerCommentsReload();
      fetchComments();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to delete comment");
    }
  };

  // Group comments into root comments and their threaded replies
  const rootComments = comments.filter((c) => !c.parent_comment_id);
  const getReplies = (parentId: string) => comments.filter((c) => c.parent_comment_id === parentId);

  return (
    <div className="comments-panel">
      <div className="comments-panel-header">
        <h3>💬 Comments &amp; Annotations</h3>
      </div>

      {error && <div className="collab-error-banner">{error}</div>}

      <form onSubmit={handleSubmitComment} className="comment-input-form">
        <textarea
          required
          rows={2}
          value={newCommentText}
          onChange={(e) => setNewCommentText(e.target.value)}
          placeholder="Add a comment or question..."
        />
        <div className="comment-form-actions">
          <button type="submit" className="ws-btn primary small">Comment</button>
        </div>
      </form>

      {loading && comments.length === 0 ? (
        <div className="comments-loading">Loading comments...</div>
      ) : comments.length === 0 ? (
        <div className="comments-empty">No comments yet. Start the conversation!</div>
      ) : (
        <div className="comments-list-container">
          {rootComments.map((comment) => {
            const replies = getReplies(comment.id);
            return (
              <div key={comment.id} className={`comment-card ${comment.is_resolved ? "resolved" : ""}`}>
                <div className="comment-header">
                  <div className="comment-author">
                    <span className="author-avatar">👤</span>
                    <span className="author-name">User: {comment.author_id}</span>
                  </div>
                  <div className="comment-meta">
                    <span className="comment-time">{new Date(comment.created_at).toLocaleTimeString()}</span>
                    {comment.is_edited && <span className="comment-edited-label">(edited)</span>}
                  </div>
                </div>

                {editingCommentId === comment.id ? (
                  <div className="comment-edit-box">
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                    />
                    <div className="comment-edit-actions">
                      <button className="ws-btn ghost small" onClick={() => setEditingCommentId(null)}>Cancel</button>
                      <button className="ws-btn primary small" onClick={() => handleEditComment(comment.id)}>Save</button>
                    </div>
                  </div>
                ) : (
                  <div className="comment-content">{comment.content}</div>
                )}

                {comment.is_resolved && (
                  <div className="comment-resolved-badge">
                    ✓ Resolved by {comment.resolved_by}
                  </div>
                )}

                <div className="comment-actions">
                  {!comment.is_resolved && (
                    <button className="comment-action-link" onClick={() => setReplyingTo(comment.id)}>
                      Reply
                    </button>
                  )}
                  {comment.author_id === user?.id && !comment.is_resolved && (
                    <button
                      className="comment-action-link"
                      onClick={() => {
                        setEditingCommentId(comment.id);
                        setEditText(comment.content);
                      }}
                    >
                      Edit
                    </button>
                  )}
                  {!comment.is_resolved && (
                    <button className="comment-action-link resolve" onClick={() => handleResolveComment(comment.id)}>
                      Resolve
                    </button>
                  )}
                  {(comment.author_id === user?.id) && (
                    <button className="comment-action-link delete" onClick={() => handleDeleteComment(comment.id)}>
                      Delete
                    </button>
                  )}
                </div>

                {/* Replies container */}
                {replies.length > 0 && (
                  <div className="comment-replies-list">
                    {replies.map((reply) => (
                      <div key={reply.id} className="comment-card reply">
                        <div className="comment-header">
                          <div className="comment-author">
                            <span className="author-avatar">👤</span>
                            <span className="author-name">User: {reply.author_id}</span>
                          </div>
                          <span className="comment-time">{new Date(reply.created_at).toLocaleTimeString()}</span>
                        </div>
                        <div className="comment-content">{reply.content}</div>
                        <div className="comment-actions">
                          {reply.author_id === user?.id && (
                            <button
                              className="comment-action-link delete"
                              onClick={() => handleDeleteComment(reply.id)}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Reply Form */}
                {replyingTo === comment.id && (
                  <div className="reply-input-box">
                    <textarea
                      placeholder="Write a reply..."
                      value={replyText[comment.id] || ""}
                      onChange={(e) =>
                        setReplyText((prev) => ({ ...prev, [comment.id]: e.target.value }))
                      }
                    />
                    <div className="reply-actions">
                      <button className="ws-btn ghost small" onClick={() => setReplyingTo(null)}>Cancel</button>
                      <button className="ws-btn primary small" onClick={() => handleAddReply(comment.id)}>Reply</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
