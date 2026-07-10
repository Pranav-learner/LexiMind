// Owns a single conversation's message state: history (paginated, infinite-scroll upward), the
// live streaming turn, and the send / cancel / regenerate actions. Streaming is driven by
// `streamMessage` (fetch POST + SSE reader). Cancellation aborts the reader and reloads history so
// the UI never desyncs from the server (the user turn is persisted server-side before the abort).

import { useCallback, useEffect, useRef, useState } from "react";
import * as chatApi from "../../api/chat";
import { ApiError } from "../../api/client";
import type { ChatMessage } from "../../types";

const PAGE_SIZE = 30;
const OPTIMISTIC_USER = "__optimistic_user__";
const STREAMING_ASSISTANT = "__streaming_assistant__";

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

// A minimal placeholder message shaped like the real DTO.
function placeholder(id: string, role: "user" | "assistant", content: string, convId: string): ChatMessage {
  return {
    id,
    conversation_id: convId,
    role,
    content,
    token_usage: null,
    latency_ms: null,
    retrieval_ms: null,
    context_size: null,
    citation_count: 0,
    meta: null,
    created_at: new Date().toISOString(),
    citations: [],
  };
}

export function useChat(ws: string, conversationId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const oldestPageRef = useRef(1);
  const streamAbortRef = useRef<AbortController | null>(null);
  const loadAbortRef = useRef<AbortController | null>(null);
  const streamingRef = useRef(false);
  streamingRef.current = streaming;

  const streamingIdRef = useRef<string | null>(null);

  // ---- history load ----------------------------------------------------
  const reloadHistory = useCallback(
    async (silent = false) => {
      if (!conversationId) return;
      loadAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      if (!silent) setLoadingHistory(true);
      try {
        const first = await chatApi.listMessages(ws, conversationId, 1, PAGE_SIZE, controller.signal);
        // Backend paginates oldest→newest, so the newest turns live on the LAST page.
        const lastPage = Math.max(1, first.pages);
        const target =
          lastPage === first.page
            ? first
            : await chatApi.listMessages(ws, conversationId, lastPage, PAGE_SIZE, controller.signal);
        setMessages(target.items);
        oldestPageRef.current = lastPage;
        setHasMore(lastPage > 1);
      } catch (err) {
        if (isAbort(err)) return;
        setError(err instanceof ApiError ? err.message : "Failed to load messages.");
      } finally {
        if (!silent) setLoadingHistory(false);
      }
    },
    [ws, conversationId],
  );

  // Load the conversation's messages when it changes.
  useEffect(() => {
    setMessages([]);
    setError(null);
    setHasMore(false);
    oldestPageRef.current = 1;
    if (!conversationId) return;
    reloadHistory();
    return () => {
      loadAbortRef.current?.abort();
      streamAbortRef.current?.abort();
    };
  }, [conversationId, reloadHistory]);

  // Load an older page and prepend it (infinite scroll upward).
  const loadOlder = useCallback(async () => {
    if (!conversationId || loadingOlder || oldestPageRef.current <= 1) return;
    const prevPage = oldestPageRef.current - 1;
    setLoadingOlder(true);
    try {
      const res = await chatApi.listMessages(ws, conversationId, prevPage, PAGE_SIZE);
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        const older = res.items.filter((m) => !seen.has(m.id));
        return [...older, ...prev];
      });
      oldestPageRef.current = prevPage;
      setHasMore(prevPage > 1);
    } catch (err) {
      if (!isAbort(err)) setError(err instanceof ApiError ? err.message : "Failed to load older messages.");
    } finally {
      setLoadingOlder(false);
    }
  }, [ws, conversationId, loadingOlder]);

  // ---- send / stream ---------------------------------------------------
  const send = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || !conversationId || streamingRef.current) return;

      setError(null);
      streamingRef.current = true;
      setStreaming(true);
      streamingIdRef.current = STREAMING_ASSISTANT;

      // Drop any prior failed optimistic turns, then add the optimistic user + streaming assistant.
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== OPTIMISTIC_USER),
        placeholder(OPTIMISTIC_USER, "user", text, conversationId),
        placeholder(STREAMING_ASSISTANT, "assistant", "", conversationId),
      ]);

      const controller = new AbortController();
      streamAbortRef.current = controller;
      let sawError: string | null = null;

      try {
        await chatApi.streamMessage(ws, conversationId, text, {
          signal: controller.signal,
          onEvent: (ev) => {
            if (ev.type === "user") {
              const real = ev.data;
              setMessages((prev) => prev.map((m) => (m.id === OPTIMISTIC_USER ? real : m)));
            } else if (ev.type === "token") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === STREAMING_ASSISTANT ? { ...m, content: m.content + ev.data.text } : m,
                ),
              );
            } else if (ev.type === "done") {
              const real = ev.data;
              setMessages((prev) => prev.map((m) => (m.id === STREAMING_ASSISTANT ? real : m)));
              streamingIdRef.current = null;
            } else if (ev.type === "error") {
              sawError = ev.data.message || ev.data.error || "The assistant failed to respond.";
            }
          },
        });
      } catch (err) {
        if (isAbort(err)) {
          // Cancelled by the user — reload from the server so the persisted user turn shows.
          setStreaming(false);
          streamingRef.current = false;
          streamingIdRef.current = null;
          await reloadHistory(true);
          return;
        }
        sawError = err instanceof ApiError ? err.message : "The assistant failed to respond.";
      }

      setStreaming(false);
      streamingRef.current = false;

      if (sawError) {
        setError(sawError);
        // Mark the user turn as failed (Retry) and drop the empty assistant bubble.
        setMessages((prev) =>
          prev
            .filter((m) => m.id !== STREAMING_ASSISTANT)
            .map((m) =>
              m.id === OPTIMISTIC_USER ? { ...m, meta: { ...(m.meta || {}), status: "error" } } : m,
            ),
        );
      } else if (streamingIdRef.current === STREAMING_ASSISTANT) {
        // Stream ended without a `done` event — reconcile with the server.
        streamingIdRef.current = null;
        await reloadHistory(true);
      }
    },
    [ws, conversationId, reloadHistory],
  );

  // Stop generating: abort the reader. `send` handles the reload on abort.
  const cancel = useCallback(() => {
    streamAbortRef.current?.abort();
  }, []);

  // Regenerate: resend the user message preceding the given assistant message.
  const regenerate = useCallback(
    (assistant: ChatMessage) => {
      const idx = messages.findIndex((m) => m.id === assistant.id);
      for (let i = idx - 1; i >= 0; i--) {
        if (messages[i].role === "user") {
          send(messages[i].content);
          return;
        }
      }
    },
    [messages, send],
  );

  // Edit a user message → resend the edited text as a new turn.
  const editMessage = useCallback((_message: ChatMessage, next: string) => send(next), [send]);

  // Retry a failed user turn.
  const retry = useCallback((message: ChatMessage) => send(message.content), [send]);

  return {
    messages,
    streaming,
    streamingId: STREAMING_ASSISTANT,
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
    clearError: useCallback(() => setError(null), []),
  };
}
