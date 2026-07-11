// The notes dashboard toolbar: search, type filter, pinned/favorite/archived filters, and sort.
// Purely controlled — every change bubbles up so NotesDashboard owns the query state.

import type {
  NoteArchivedFilter,
  NotePinnedFilter,
  NoteSortField,
  NoteType,
  SortOrder,
} from "../../types";
import { NOTE_TYPES, NOTE_TYPE_META } from "./constants";

interface Props {
  search: string;
  onSearch: (v: string) => void;
  type: NoteType | "";
  onType: (v: NoteType | "") => void;
  pinned: NotePinnedFilter;
  onPinned: (v: NotePinnedFilter) => void;
  archived: NoteArchivedFilter;
  onArchived: (v: NoteArchivedFilter) => void;
  sortBy: NoteSortField;
  order: SortOrder;
  onSort: (f: NoteSortField, o: SortOrder) => void;
}

export default function NotesToolbar({
  search, onSearch, type, onType, pinned, onPinned, archived, onArchived, sortBy, order, onSort,
}: Props) {
  return (
    <div className="sum-toolbar note-toolbar-row">
      <div className="sum-search">
        <span aria-hidden="true">🔍</span>
        <input
          type="search"
          placeholder="Search notes by title or content…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          aria-label="Search notes"
        />
      </div>

      <select value={type} onChange={(e) => onType(e.target.value as NoteType | "")} aria-label="Filter by type">
        <option value="">All types</option>
        {NOTE_TYPES.map((t) => (
          <option key={t} value={t}>{NOTE_TYPE_META[t].icon} {NOTE_TYPE_META[t].label}</option>
        ))}
      </select>

      <select value={pinned} onChange={(e) => onPinned(e.target.value as NotePinnedFilter)} aria-label="Pinned filter">
        <option value="any">All notes</option>
        <option value="pinned">📌 Pinned</option>
        <option value="favorite">⭐ Favorites</option>
      </select>

      <select value={archived} onChange={(e) => onArchived(e.target.value as NoteArchivedFilter)} aria-label="Archived filter">
        <option value="active">Active</option>
        <option value="archived">Archived</option>
        <option value="all">All</option>
      </select>

      <select
        value={`${sortBy}:${order}`}
        onChange={(e) => {
          const [f, o] = e.target.value.split(":");
          onSort(f as NoteSortField, o as SortOrder);
        }}
        aria-label="Sort notes"
      >
        <option value="updated_at:desc">Recently updated</option>
        <option value="created_at:desc">Newest</option>
        <option value="last_opened_at:desc">Recently opened</option>
        <option value="title:asc">Title A–Z</option>
        <option value="word_count:desc">Longest</option>
      </select>
    </div>
  );
}
