// Search + type filter + status filter + sort + order controls for the Summaries dashboard.
// Purely presentational: it reports changes upward; the dashboard owns the query state and
// data fetching.

import type {
  SortOrder,
  SummarySortField,
  SummaryStatusFilter,
  SummaryType,
} from "../../types";
import { SUMMARY_SORTS, SUMMARY_TYPES } from "./constants";

interface Props {
  search: string;
  onSearch: (v: string) => void;
  type: SummaryType | "";
  onType: (v: SummaryType | "") => void;
  status: SummaryStatusFilter;
  onStatus: (v: SummaryStatusFilter) => void;
  sortBy: SummarySortField;
  order: SortOrder;
  onSort: (field: SummarySortField, order: SortOrder) => void;
}

const STATUSES: { value: SummaryStatusFilter; label: string }[] = [
  { value: "any", label: "All statuses" },
  { value: "completed", label: "Ready" },
  { value: "processing", label: "Generating" },
  { value: "queued", label: "Queued" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export default function SummaryToolbar({
  search,
  onSearch,
  type,
  onType,
  status,
  onStatus,
  sortBy,
  order,
  onSort,
}: Props) {
  return (
    <div className="ws-toolbar sum-toolbar">
      <input
        className="ws-search"
        type="search"
        placeholder="Search summaries…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />

      <div className="ws-toolbar-right">
        <select
          className="ws-select"
          value={type}
          onChange={(e) => onType(e.target.value as SummaryType | "")}
          aria-label="Type filter"
        >
          <option value="">All types</option>
          {SUMMARY_TYPES.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>

        <select
          className="ws-select"
          value={status}
          onChange={(e) => onStatus(e.target.value as SummaryStatusFilter)}
          aria-label="Status filter"
        >
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        <select
          className="ws-select"
          value={`${sortBy}:${order}`}
          onChange={(e) => {
            const [field, ord] = e.target.value.split(":") as [SummarySortField, SortOrder];
            onSort(field, ord);
          }}
          aria-label="Sort summaries"
        >
          {SUMMARY_SORTS.map((s) => (
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
      </div>
    </div>
  );
}
