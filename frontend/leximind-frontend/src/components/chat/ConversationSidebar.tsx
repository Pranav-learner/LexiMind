// The conversation list rail for the chat workspace. Owns its own query state: a debounced (300ms)
// search that hits the broad /search endpoint, an Archived toggle, and a paginated list grouped
// into Pinned / Recent. Each row has a kebab menu (Rename, Pin/Unpin, Duplicate, Archive/Restore,
// Delete). Selecting a row navigates via the parent's onSelect. Re-fetches when `reloadSignal`
// changes (e.g. after a new message updates last_message_at).

import { useCallback, useEffect, useRef, useState } from "react";
import * as chatApi from "../../api/chat";
import { ApiError } from "../../api/client";
import { relativeTime } from "../document/constants";
import type { Conversation, ConversationArchivedFilter } from "../../types";

const PAGE_SIZE = 30;

interface Props {
  ws: string;
  activeId: string | null;
  reloadSignal: number;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function ConversationSidebar({ ws, activeId, reloadSignal, onSelect, onNew }: Props) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState<ConversationArchivedFilter>("active");
  const [menuId, setMenuId] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // Debounce the search box.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      if (search) {
        const res = await chatApi.searchConversations(ws, search, 30, controller.signal);
        setItems(res);
      } else {
        const res = await chatApi.listConversations(
          ws,
          { page: 1, page_size: PAGE_SIZE, archived, sort_by: "last_message_at", order: "desc" },
          controller.signal,
        );
        setItems(res.items);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load conversations.");
    } finally {
      setLoading(false);
    }
  }, [ws, search, archived]);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load, reloadSignal]);

  async function mutate(fn: () => Promise<unknown>) {
    setMenuId(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  function rename(c: Conversation) {
    const next = window.prompt("Rename conversation", c.title);
    if (next != null && next.trim() && next.trim() !== c.title) {
      mutate(() => chatApi.updateConversation(ws, c.id, { title: next.trim() }));
    } else {
      setMenuId(null);
    }
  }

  function confirmDelete(c: Conversation) {
    if (window.confirm(`Delete "${c.title}"? This cannot be undone.`)) {
      mutate(() => chatApi.deleteConversation(ws, c.id, true));
    } else {
      setMenuId(null);
    }
  }

  async function duplicate(c: Conversation) {
    setMenuId(null);
    try {
      const dup = await chatApi.duplicateConversation(ws, c.id);
      await load();
      onSelect(dup.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Duplicate failed.");
    }
  }

  const pinned = items.filter((c) => c.is_pinned);
  const rest = items.filter((c) => !c.is_pinned);

  const renderRow = (c: Conversation) => (
    <ConversationRow
      key={c.id}
      c={c}
      active={c.id === activeId}
      menuOpen={menuId === c.id}
      onSelect={() => onSelect(c.id)}
      onToggleMenu={() => setMenuId((m) => (m === c.id ? null : c.id))}
      onCloseMenu={() => setMenuId(null)}
      onRename={() => rename(c)}
      onPin={() => mutate(() => (c.is_pinned ? chatApi.unpinConversation(ws, c.id) : chatApi.pinConversation(ws, c.id)))}
      onDuplicate={() => duplicate(c)}
      onArchive={() => mutate(() => (c.is_archived ? chatApi.restoreConversation(ws, c.id) : chatApi.archiveConversation(ws, c.id)))}
      onDelete={() => confirmDelete(c)}
    />
  );

  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar-top">
        <button className="ws-btn primary chat-new-btn" onClick={onNew} title="Start a new chat">
          ✚ New chat
        </button>
      </div>

      <div className="chat-search">
        <input
          className="chat-search-input"
          type="search"
          placeholder="Search conversations…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          aria-label="Search conversations"
        />
      </div>

      <div className="chat-archived-toggle">
        <button
          className={`chat-chip${archived === "active" ? " on" : ""}`}
          onClick={() => setArchived("active")}
        >
          Active
        </button>
        <button
          className={`chat-chip${archived === "archived" ? " on" : ""}`}
          onClick={() => setArchived("archived")}
        >
          Archived
        </button>
        <button
          className={`chat-chip${archived === "all" ? " on" : ""}`}
          onClick={() => setArchived("all")}
        >
          All
        </button>
      </div>

      {error && <div className="ws-error-banner chat-sidebar-error">{error}</div>}

      <div className="chat-conv-list">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => <div key={i} className="chat-conv-row skeleton" />)
        ) : items.length === 0 ? (
          <div className="chat-conv-empty">
            {search ? "No conversations match." : "No conversations yet."}
          </div>
        ) : (
          <>
            {pinned.length > 0 && !search && (
              <>
                <div className="chat-conv-group">📌 Pinned</div>
                {pinned.map(renderRow)}
                <div className="chat-conv-group">Recent</div>
              </>
            )}
            {(search ? items : rest).map(renderRow)}
          </>
        )}
      </div>
    </aside>
  );
}

interface RowProps {
  c: Conversation;
  active: boolean;
  menuOpen: boolean;
  onSelect: () => void;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onRename: () => void;
  onPin: () => void;
  onDuplicate: () => void;
  onArchive: () => void;
  onDelete: () => void;
}

function ConversationRow({
  c,
  active,
  menuOpen,
  onSelect,
  onToggleMenu,
  onCloseMenu,
  onRename,
  onPin,
  onDuplicate,
  onArchive,
  onDelete,
}: RowProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onCloseMenu();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseMenu();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, onCloseMenu]);

  return (
    <div
      className={`chat-conv-row${active ? " active" : ""}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
    >
      <div className="chat-conv-main">
        <div className="chat-conv-title">
          {c.is_pinned && <span className="chat-conv-pin" aria-hidden="true">📌</span>}
          {c.title || "Untitled chat"}
        </div>
        <div className="chat-conv-meta">
          {relativeTime(c.last_message_at || c.updated_at)} · {c.message_count} msg
        </div>
      </div>
      <div className="chat-conv-menu-wrap" ref={menuRef}>
        <button
          className="ws-icon-btn chat-kebab"
          title="More"
          aria-label="Conversation menu"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={(e) => {
            e.stopPropagation();
            onToggleMenu();
          }}
        >
          ⋯
        </button>
        {menuOpen && (
          <div className="chat-kebab-menu" role="menu" onClick={(e) => e.stopPropagation()}>
            <button role="menuitem" onClick={onRename}>✏️ Rename</button>
            <button role="menuitem" onClick={onPin}>{c.is_pinned ? "📌 Unpin" : "📌 Pin"}</button>
            <button role="menuitem" onClick={onDuplicate}>📄 Duplicate</button>
            <button role="menuitem" onClick={onArchive}>
              {c.is_archived ? "♻️ Restore" : "📥 Archive"}
            </button>
            <button role="menuitem" className="danger" onClick={onDelete}>🗑️ Delete</button>
          </div>
        )}
      </div>
    </div>
  );
}
