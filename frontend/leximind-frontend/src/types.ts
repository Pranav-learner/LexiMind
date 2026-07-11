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

// -------------------------------------------------------------- summaries
// Contracts for AI Summaries (Phase 3, Module 5). Generation is asynchronous: a
// created summary starts queued/processing and is polled via GET /{id}/status until
// it reaches a terminal state. NOTE: the section type is named `SummarySectionT`
// (never `SummarySection`) to avoid any collision, and a citation's `document_id` is
// the VECTOR document id (resolve via GET .../documents/by-vector/{document_id}).

export type SummaryType = "quick" | "standard" | "detailed" | "bullet" | "chapterwise";
export type SummaryStatus =
  | "queued"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";
export type SummaryScope = "document" | "multi" | "workspace";

export type SummaryStatusFilter = "any" | SummaryStatus;
export type SummarySortField = "created_at" | "updated_at" | "title";

export interface Summary {
  id: string;
  workspace_id: string;
  owner_id: string;
  scope: SummaryScope;
  document_id: string | null;
  document_ids: string[] | null;
  conversation_id: string | null;
  title: string;
  summary_type: SummaryType;
  language: string;
  status: SummaryStatus;
  progress: number; // 0–100
  stage: string;
  error: string | null;
  model_name: string;
  prompt_version: string;
  token_usage: unknown;
  generation_ms: number | null;
  section_count: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SummaryCitation {
  id: string;
  document_id: string; // VECTOR document id
  chunk_id: string;
  page_number: number;
  workspace_id: string;
  citation_text: string;
  confidence: number;
}

export interface SummarySectionT {
  id: string;
  heading: string;
  order: number;
  content: string; // Markdown
  citation_count: number;
  citations: SummaryCitation[];
}

export type SummaryDetail = Summary & { sections: SummarySectionT[] };

export interface SummaryListResponse {
  items: Summary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface SummaryListParams {
  page?: number;
  page_size?: number;
  search?: string;
  summary_type?: SummaryType | "";
  status?: SummaryStatusFilter;
  document_id?: string;
  sort_by?: SummarySortField;
  order?: SortOrder;
}

export interface SummaryCreateInput {
  summary_type: SummaryType;
  scope?: SummaryScope;
  document_id?: string;
  document_ids?: string[];
  title?: string;
  top_k?: number;
}

// ----------------------------------------------------------------- notes
// Contracts for the Smart Notes Engine (Phase 3, Module 6). Notes are persistent, editable,
// user-owned knowledge assets. AI generation is asynchronous (poll GET /{id}/status until
// terminal); manual notes are born `ready`. A citation's `document_id` is the VECTOR document id
// (resolve via GET .../documents/by-vector/{document_id}). NOTE: the section type is
// `NoteSectionT` to avoid any collision.

export type NoteType = "quick" | "study" | "detailed" | "chapterwise" | "concept" | "revision";
export type NoteStatus =
  | "ready"
  | "queued"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";
export type NoteSource = "blank" | "document" | "summary" | "chat" | "selection";
export type NoteScope = "document" | "multi" | "workspace";

export type NoteStatusFilter = "any" | NoteStatus;
export type NoteArchivedFilter = "active" | "archived" | "all";
export type NotePinnedFilter = "any" | "pinned" | "favorite";
export type NoteSortField =
  | "created_at"
  | "updated_at"
  | "last_opened_at"
  | "title"
  | "word_count";

export interface Tag {
  id: string;
  workspace_id: string;
  name: string;
  color: string;
  note_count: number;
}

export interface NoteCitationT {
  id: string;
  note_section_id: string | null;
  document_id: string | null; // VECTOR document id
  chunk_id: string | null;
  page_number: number | null;
  workspace_id: string;
  citation_text: string;
  confidence: number | null;
}

export interface NoteSectionT {
  id: string;
  heading: string;
  order: number;
  content: string;
  citation_count: number;
}

export interface OutlineItem {
  level: number;
  text: string;
  slug: string;
}

export interface Note {
  id: string;
  workspace_id: string;
  owner_id: string;
  document_id: string | null;
  conversation_id: string | null;
  folder_id: string | null;
  source: NoteSource;
  note_type: NoteType | null;
  title: string;
  description: string;
  editor_format: string;
  status: NoteStatus;
  progress: number;
  stage: string;
  error: string | null;
  created_by: string;
  is_pinned: boolean;
  is_favorite: boolean;
  is_archived: boolean;
  word_count: number;
  reading_time: number;
  section_count: number;
  citation_count: number;
  model_name: string;
  token_usage: number;
  generation_ms: number;
  version: number;
  last_opened_at: string | null;
  created_at: string;
  updated_at: string;
  tags: Tag[];
}

export type NoteDetail = Note & {
  content: string; // canonical editable Markdown body
  sections: NoteSectionT[];
  citations: NoteCitationT[];
  outline: OutlineItem[];
};

export interface NoteListResponse {
  items: Note[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface NoteListParams {
  page?: number;
  page_size?: number;
  search?: string;
  note_type?: NoteType | "";
  source?: NoteSource | "";
  document_id?: string;
  conversation_id?: string;
  tag_id?: string;
  status?: NoteStatusFilter;
  archived?: NoteArchivedFilter;
  pinned?: NotePinnedFilter;
  sort_by?: NoteSortField;
  order?: SortOrder;
}

export interface NoteCreateInput {
  title?: string;
  description?: string;
  content?: string;
  source?: NoteSource;
  document_id?: string;
  conversation_id?: string;
  tags?: string[];
  citations?: Array<{
    document_id?: string;
    chunk_id?: string;
    page_number?: number;
    citation_text?: string;
    confidence?: number;
  }>;
}

export interface NoteGenerateInput {
  note_type: NoteType;
  scope?: NoteScope;
  document_id?: string;
  document_ids?: string[];
  conversation_id?: string;
  title?: string;
  subject?: string;
}

export interface NoteMetaUpdateInput {
  title?: string;
  description?: string;
  is_pinned?: boolean;
  is_favorite?: boolean;
  is_archived?: boolean;
}

export type AssistOperation =
  | "rewrite"
  | "expand"
  | "simplify"
  | "grammar"
  | "examples"
  | "quiz"
  | "flashcards"
  | "summarize";

export interface AssistResponse {
  operation: AssistOperation;
  result: string;
}

export interface TagListResponse {
  items: Tag[];
  total: number;
}

// ----------------------------------------------------------------- flashcards
// Contracts for the AI Flashcards & Active Recall Engine (Phase 3, Module 7). Decks generate
// asynchronously (poll GET /decks/{id}/status). Cards carry SM-2 spaced-repetition state. A
// citation's `document_id` is the VECTOR document id (resolve via GET .../documents/by-vector/{id}).

export type CardType = "basic" | "definition" | "cloze" | "truefalse";
export type CardTypePref = "mixed" | CardType;
export type DeckStatus = "ready" | "queued" | "processing" | "completed" | "failed" | "cancelled";
export type DeckScope = "manual" | "document" | "multi" | "workspace";
export type CardStatus = "active" | "suspended" | "archived";
export type ReviewRating = "again" | "hard" | "good" | "easy";
export type LearningStage = "new" | "learning" | "review" | "relearning";

export interface DeckStats {
  total: number;
  new: number;
  due: number;
  learning: number;
  review: number;
  suspended: number;
  mastered: number;
  avg_mastery: number;
}

export interface Deck {
  id: string;
  workspace_id: string;
  owner_id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  scope: DeckScope;
  document_id: string | null;
  note_id: string | null;
  summary_id: string | null;
  conversation_id: string | null;
  subject: string | null;
  card_type_pref: CardTypePref;
  status: DeckStatus;
  progress: number;
  stage: string;
  error: string | null;
  created_by: string;
  card_count: number;
  is_archived: boolean;
  is_public: boolean;
  model_name: string;
  generation_ms: number;
  created_at: string;
  updated_at: string;
  stats?: DeckStats | null;
}

export interface FlashcardCitationT {
  id: string;
  document_id: string | null;
  chunk_id: string | null;
  page_number: number | null;
  workspace_id: string;
  citation_text: string;
  confidence: number | null;
}

export interface Flashcard {
  id: string;
  workspace_id: string;
  owner_id: string;
  deck_id: string;
  document_id: string | null;
  note_id: string | null;
  summary_id: string | null;
  conversation_id: string | null;
  front: string;
  back: string;
  hint: string;
  card_type: CardType;
  extra: Record<string, unknown> | null;
  difficulty: string;
  created_by: string;
  status: CardStatus;
  is_favorite: boolean;
  learning_stage: LearningStage;
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  review_count: number;
  lapse_count: number;
  correct_count: number;
  mastery_score: number;
  citation_count: number;
  last_reviewed_at: string | null;
  next_review_at: string | null;
  created_at: string;
  updated_at: string;
}

export type FlashcardDetail = Flashcard & { citations: FlashcardCitationT[] };

export interface DeckListResponse {
  items: Deck[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface FlashcardListResponse {
  items: Flashcard[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ReviewButton {
  rating: ReviewRating;
  interval_days: number;
  label: string;
}

export interface ReviewCardT {
  card: FlashcardDetail;
  buttons: ReviewButton[];
}

export interface ReviewQueue {
  deck_id: string | null;
  total_due: number;
  new_count: number;
  due_count: number;
  cards: ReviewCardT[];
}

export interface ReviewResult {
  card: Flashcard;
  rating: ReviewRating;
  scheduled_interval: number;
  next_review_at: string | null;
  mastery_score: number;
}

export interface DailyActivity {
  date: string;
  reviews: number;
  correct: number;
}

export interface LearningAnalytics {
  total_cards: number;
  active_cards: number;
  new_cards: number;
  due_today: number;
  mastered_cards: number;
  suspended_cards: number;
  reviews_today: number;
  reviews_total: number;
  accuracy: number;
  retention: number;
  avg_response_time_ms: number;
  study_streak_days: number;
  avg_mastery: number;
  daily_activity: DailyActivity[];
  deck_count: number;
}

export interface DeckGenerateInput {
  name?: string;
  scope?: DeckScope;
  document_id?: string;
  document_ids?: string[];
  note_id?: string;
  summary_id?: string;
  conversation_id?: string;
  subject?: string;
  card_type_pref?: CardTypePref;
  count?: number;
  deck_id?: string;
}

export interface CardCreateInput {
  deck_id?: string;
  front: string;
  back?: string;
  hint?: string;
  card_type?: CardType;
  difficulty?: string;
  document_id?: string;
  note_id?: string;
  summary_id?: string;
  conversation_id?: string;
  citations?: Array<{
    document_id?: string;
    chunk_id?: string;
    page_number?: number;
    citation_text?: string;
    confidence?: number;
  }>;
}

export interface DeckListParams {
  page?: number;
  page_size?: number;
  search?: string;
  archived?: "active" | "archived" | "all";
  sort_by?: "created_at" | "updated_at" | "name" | "card_count";
  order?: SortOrder;
}

// ----------------------------------------------------------------- citation intelligence
// Contracts for Citation Intelligence & Knowledge Explorer (Phase 3, Module 8). A derived index
// over Modules 4–7 citations. `document_id` is the VECTOR document id (resolve via
// GET .../documents/by-vector/{id}).

export type CitationReferenceType = "message" | "summary" | "note" | "flashcard";

export interface CitationRef {
  id: string;
  reference_type: CitationReferenceType;
  message_id: string | null;
  summary_id: string | null;
  note_id: string | null;
  flashcard_id: string | null;
  ref_parent_id: string | null;   // conversation / summary / note / deck id (navigation target)
  ref_child_id: string | null;    // message / section / card id
  ref_title: string;
}

export interface CitationIntel {
  id: string;
  workspace_id: string;
  document_id: string | null;
  chunk_id: string | null;
  page_number: number | null;
  paragraph_number: number | null;
  citation_text: string;
  confidence: number | null;
  retrieval_score: number | null;
  reranker_score: number | null;
  evidence_score: number | null;
  reference_count: number;
  created_at: string;
}

export interface CitationDocumentContext {
  document_id: string | null;
  citation_count: number;
  reference_count: number;
}

export type CitationDetail = CitationIntel & {
  references: CitationRef[];
  references_by_type: Record<string, number>;
  document: CitationDocumentContext | null;
};

export interface RelatedCitation {
  citation_id: string | null;
  chunk_id: string | null;
  document_id: string | null;
  relationship: "co_reference" | "same_document" | string;
  strength: number;
  page_number: number | null;
  citation_text: string;
}

export interface RelatedKnowledge {
  citation_id: string;
  related: RelatedCitation[];
  references_by_type: Record<string, number>;
  same_document_citations: CitationIntel[];
}

export interface ExplainFactor {
  label: string;
  detail: string;
  score: number | null;
}

export interface CitationExplanation {
  citation_id: string;
  summary: string;
  factors: ExplainFactor[];
  retrieval_path: string[];
}

export interface CitationStats {
  total_citations: number;
  total_references: number;
  documents_cited: number;
  avg_confidence: number;
  high_confidence: number;
  references_by_type: Record<string, number>;
  most_referenced: CitationIntel[];
}

export interface CitationListResponse {
  items: CitationIntel[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CitationSearchParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  document_id?: string;
  page_number?: number;
  reference_type?: CitationReferenceType;
  min_confidence?: number;
  sort_by?: "confidence" | "reference_count" | "created_at" | "page_number";
  order?: SortOrder;
}
