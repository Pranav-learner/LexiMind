// Search + sort + archived-filter controls for the dashboard. Purely presentational: it
// reports changes upward; the dashboard owns the query state and data fetching.

import type { ArchivedFilter, SortField, SortOrder } from "../../types";

interface Props {
  search: string;
  onSearch: (v: string) => void;
  archived: ArchivedFilter;
  onArchived: (v: ArchivedFilter) => void;
  sortBy: SortField;
  order: SortOrder;
  onSort: (field: SortField, order: SortOrder) => void;
}

const SORTS: { label: string; field: SortField; order: SortOrder }[] = [
  { label: "Recently updated", field: "updated_at", order: "desc" },
  { label: "Newest", field: "created_at", order: "desc" },
  { label: "Name (A–Z)", field: "name", order: "asc" },
  { label: "Most documents", field: "document_count", order: "desc" },
];

export default function WorkspaceToolbar({
  search,
  onSearch,
  archived,
  onArchived,
  sortBy,
  order,
  onSort,
}: Props) {
  return (
    <div className="ws-toolbar">
      <input
        className="ws-search"
        type="search"
        placeholder="Search workspaces…"
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
          value={`${sortBy}:${order}`}
          onChange={(e) => {
            const [field, ord] = e.target.value.split(":") as [SortField, SortOrder];
            onSort(field, ord);
          }}
        >
          {SORTS.map((s) => (
            <option key={`${s.field}:${s.order}`} value={`${s.field}:${s.order}`}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
