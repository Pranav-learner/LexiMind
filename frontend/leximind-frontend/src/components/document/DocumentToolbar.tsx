// Search + filter + sort + view controls for the Document Library. Purely presentational: it
// reports changes upward; the library page owns the query state and data fetching.

import type {
  ArchivedFilter,
  DocumentSortField,
  IndexedFilter,
  SortOrder,
} from "../../types";
import { DOCUMENT_SORTS } from "./constants";

interface Props {
  search: string;
  onSearch: (v: string) => void;
  archived: ArchivedFilter;
  onArchived: (v: ArchivedFilter) => void;
  indexed: IndexedFilter;
  onIndexed: (v: IndexedFilter) => void;
  fileType: string;
  onFileType: (v: string) => void;
  language: string;
  onLanguage: (v: string) => void;
  sortBy: DocumentSortField;
  order: SortOrder;
  onSort: (field: DocumentSortField, order: SortOrder) => void;
  view: "grid" | "list";
  onView: (v: "grid" | "list") => void;
  fileTypes: string[];
  languages: string[];
}

export default function DocumentToolbar({
  search,
  onSearch,
  archived,
  onArchived,
  indexed,
  onIndexed,
  fileType,
  onFileType,
  language,
  onLanguage,
  sortBy,
  order,
  onSort,
  view,
  onView,
  fileTypes,
  languages,
}: Props) {
  return (
    <div className="ws-toolbar doc-toolbar">
      <input
        className="ws-search"
        type="search"
        placeholder="Search documents…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />

      <div className="ws-toolbar-right">
        <div className="ws-segment">
          {(["active", "archived", "all"] as ArchivedFilter[]).map((f) => (
            <button
              key={f}
              className={archived === f ? "active" : ""}
              onClick={() => onArchived(f)}
            >
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        <select
          className="ws-select"
          value={indexed}
          onChange={(e) => onIndexed(e.target.value as IndexedFilter)}
          aria-label="Index filter"
        >
          <option value="any">All index states</option>
          <option value="indexed">Indexed</option>
          <option value="unindexed">Unindexed</option>
        </select>

        <select
          className="ws-select"
          value={fileType}
          onChange={(e) => onFileType(e.target.value)}
          aria-label="File type filter"
        >
          <option value="">All types</option>
          {fileTypes.map((t) => (
            <option key={t} value={t}>
              {t.toUpperCase()}
            </option>
          ))}
        </select>

        <select
          className="ws-select"
          value={language}
          onChange={(e) => onLanguage(e.target.value)}
          aria-label="Language filter"
        >
          <option value="">All languages</option>
          {languages.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>

        <select
          className="ws-select"
          value={`${sortBy}:${order}`}
          onChange={(e) => {
            const [field, ord] = e.target.value.split(":") as [
              DocumentSortField,
              SortOrder,
            ];
            onSort(field, ord);
          }}
          aria-label="Sort documents"
        >
          {DOCUMENT_SORTS.map((s) => (
            <option key={`${s.field}:${s.order}`} value={`${s.field}:${s.order}`}>
              {s.label}
            </option>
          ))}
        </select>

        <button
          className="ws-icon-btn"
          title={order === "asc" ? "Ascending" : "Descending"}
          aria-label="Toggle sort order"
          onClick={() => onSort(sortBy, order === "asc" ? "desc" : "asc")}
        >
          {order === "asc" ? "↑" : "↓"}
        </button>

        <div className="ws-segment doc-view-toggle">
          <button
            className={view === "grid" ? "active" : ""}
            onClick={() => onView("grid")}
            title="Grid view"
            aria-label="Grid view"
          >
            ▦
          </button>
          <button
            className={view === "list" ? "active" : ""}
            onClick={() => onView("list")}
            title="List view"
            aria-label="List view"
          >
            ☰
          </button>
        </div>
      </div>
    </div>
  );
}
