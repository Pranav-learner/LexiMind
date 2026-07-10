// Shared TypeScript contracts mirroring the backend DTOs (app/workspaces/schemas.py,
// app/auth/schemas.py). Kept in one place so pages/components never redeclare shapes.

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  owner_id: string;
  is_archived: boolean;
  document_count: number;
  chat_count: number;
  note_count: number;
  flashcard_count: number;
  summary_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceListResponse {
  items: Workspace[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type SortField = "name" | "created_at" | "updated_at" | "document_count";
export type SortOrder = "asc" | "desc";
export type ArchivedFilter = "active" | "archived" | "all";

export interface WorkspaceFormValues {
  name: string;
  description: string;
  icon: string;
  color: string;
}

export interface ListParams {
  page?: number;
  page_size?: number;
  search?: string;
  archived?: ArchivedFilter;
  sort_by?: SortField;
  order?: SortOrder;
}
