// Shared action vocabulary for the selection toolbar and right-click context menu. Kept in one
// place so future modules (Notes, Flashcards, Summaries, Annotations) can plug new handlers into
// a single `onAction(type, text)` contract without touching the menu components.

export type ViewerActionType =
  | "ask-ai"
  | "copy"
  | "note"
  | "flashcard"
  | "highlight"
  | "summary";

export interface ViewerActionDef {
  type: ViewerActionType;
  label: string;
  icon: string;
  // Whether the action is wired up today. Stubs show a "coming soon" toast.
  live: boolean;
}

// Actions offered on the text-selection floating toolbar.
export const SELECTION_ACTIONS: ViewerActionDef[] = [
  { type: "ask-ai", label: "Ask AI", icon: "✨", live: true },
  { type: "copy", label: "Copy", icon: "⧉", live: true },
  { type: "highlight", label: "Highlight", icon: "🖍", live: true },
  { type: "note", label: "Note", icon: "📝", live: false },
  { type: "flashcard", label: "Flashcard", icon: "🎴", live: false },
];

// Actions offered on the right-click context menu.
export const CONTEXT_ACTIONS: ViewerActionDef[] = [
  { type: "copy", label: "Copy", icon: "⧉", live: true },
  { type: "highlight", label: "Highlight", icon: "🖍", live: true },
  { type: "ask-ai", label: "Ask AI", icon: "✨", live: true },
  { type: "note", label: "Create Note", icon: "📝", live: false },
  { type: "summary", label: "Generate Summary", icon: "📄", live: false },
  { type: "flashcard", label: "Generate Flashcard", icon: "🎴", live: false },
];
