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

// --------------------------------------------------------------- documents
// NOTE: named `LibraryDocument` (never `Document`) to avoid shadowing the DOM global.

export type ProcessingStatus = "uploaded" | "processing" | "ready" | "failed";
export type ProcessingStage =
  | "uploaded"
  | "text_extraction"
  | "chunking"
  | "embedding"
  | "faiss_indexing"
  | "bm25_indexing"
  | "metadata"
  | "ready";
export type IndexingStatus = "pending" | "indexed" | "stale" | "failed";

export type DocumentSortField =
  | "display_name"
  | "created_at"
  | "file_size"
  | "page_count"
  | "last_indexed_at"
  | "updated_at";
export type IndexedFilter = "any" | "indexed" | "unindexed";

export interface LibraryDocument {
  id: string;
  workspace_id: string;
  owner_id: string;
  vector_document_id: string;
  filename: string;
  display_name: string;
  description: string;
  media_type: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  page_count: number;
  word_count: number;
  chunk_count: number;
  language: string;
  embedding_model: string;
  embedding_dimension: number;
  processing_status: ProcessingStatus;
  processing_stage: ProcessingStage;
  processing_error: string | null;
  processing_ms: number | null;
  upload_progress: number;
  indexing_status: IndexingStatus;
  summary_status: string;
  ocr_status: string;
  is_archived: boolean;
  last_indexed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface IndexHealth {
  chunk_count: number;
  embedding_count: number;
  faiss_status: string;
  bm25_status: string;
  index_health: string;
}

export type LibraryDocumentDetail = LibraryDocument & {
  index_health: IndexHealth | null;
};

export interface DocumentListResponse {
  items: LibraryDocument[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface DocumentListParams {
  page?: number;
  page_size?: number;
  search?: string;
  archived?: ArchivedFilter;
  indexed?: IndexedFilter;
  file_type?: string;
  language?: string;
  sort_by?: DocumentSortField;
  order?: SortOrder;
}

export interface UploadItemResult {
  filename: string;
  success: boolean;
  error: string | null;
  document: LibraryDocument | null;
}

// ----------------------------------------------------------------- viewer
// Contracts for the Intelligent PDF Viewer (Phase 3, Module 3). Mirrors the
// backend chunk / reading-session / query-citation DTOs.

export interface PdfChunk {
  chunk_id: string;
  document_id: string;
  page_number: number;
  section: string | null;
  chunk_index: number;
  text: string;
}

export interface DocumentChunksResponse {
  document_id: string;
  vector_document_id: string;
  total: number;
  items: PdfChunk[];
}

export interface ReadingSession {
  document_id: string;
  page: number;
  scroll_top: number;
  zoom: number; // percent
  rotation: number;
  updated_at: string;
}

export interface ReadingHistoryItem {
  document_id: string;
  display_name: string;
  filename: string;
  file_type: string;
  page: number;
  page_count: number;
  updated_at: string;
}

export interface ReadingHistoryResponse {
  items: ReadingHistoryItem[];
}

// A citation returned by POST /query. NOTE: `document_id` here is the VECTOR
// document id (resolve via GET .../documents/by-vector/{document_id}).
export interface QueryCitation {
  chunk_id: string;
  document_id: string;
  source: string; // filename
  page_number: number;
  section: string | null;
  text: string;
}

export interface QueryResponse {
  question: string;
  answer: string;
  sources: string;
  citations: QueryCitation[];
  analysis?: unknown;
  retrieval?: unknown;
  context?: unknown;
}

// ------------------------------------------------------------------- chat
// Contracts for the Persistent AI Chat Workspace (Phase 3, Module 4). Mirror the
// backend conversation / message / citation DTOs. NOTE: the message type is named
// `ChatMessage` (never `Message`) to avoid shadowing the DOM global.

export interface Conversation {
  id: string;
  workspace_id: string;
  owner_id: string;
  title: string;
  description: string;
  is_pinned: boolean;
  is_archived: boolean;
  message_count: number;
  last_message_at: string | null;
  document_scope: string[] | null;
  temperature: number;
  model_name: string;
  system_prompt_version: string;
  created_at: string;
  updated_at: string;
}

export type ChatRole = "user" | "assistant" | "system";

// A citation attached to an assistant message. NOTE: `document_id` is the VECTOR
// document id (resolve via GET .../documents/by-vector/{document_id}).
export interface ChatCitation {
  id: string;
  document_id: string;
  chunk_id: string;
  page_number: number;
  workspace_id: string;
  citation_text: string;
  confidence: number;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: ChatRole;
  content: string;
  token_usage: unknown;
  latency_ms: number | null;
  retrieval_ms: number | null;
  context_size: number | null;
  citation_count: number;
  meta: { status?: string; [key: string]: unknown } | null;
  created_at: string;
  citations: ChatCitation[];
}

export interface ConversationListResponse {
  items: Conversation[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface MessageListResponse {
  items: ChatMessage[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type ConversationArchivedFilter = "active" | "archived" | "all";
export type ConversationPinnedFilter = "any" | "pinned";
export type ConversationSortField =
  | "last_message_at"
  | "created_at"
  | "updated_at"
  | "title";

export interface ConversationListParams {
  page?: number;
  page_size?: number;
  search?: string;
  archived?: ConversationArchivedFilter;
  pinned?: ConversationPinnedFilter;
  sort_by?: ConversationSortField;
  order?: SortOrder;
}

export interface ConversationCreateInput {
  title?: string;
  description?: string;
  document_scope?: string[];
  temperature?: number;
  model_name?: string;
}

export type ConversationUpdateInput = ConversationCreateInput;

// SSE events streamed by POST /conversations/{id}/messages/stream.
export type ChatStreamEvent =
  | { type: "user"; data: ChatMessage }
  | { type: "token"; data: { text: string } }
  | { type: "done"; data: ChatMessage }
  | { type: "error"; data: { message?: string; error: string } };
