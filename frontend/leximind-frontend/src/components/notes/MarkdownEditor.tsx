// MarkdownEditor — LexiMind's production note editor.
//
// EDITOR CHOICE (documented in phase3_module6.md): a Markdown-based rich editor rather than a
// heavyweight WYSIWYG framework. A formatting toolbar drives a plain <textarea> "source" pane and
// a live react-markdown/GFM preview (edit · split · preview modes). Rationale: mature and
// battle-tested (GitHub/Reddit/StackOverflow), zero new npm dependencies, native Markdown
// import/export, and — crucially — editing plain Markdown can never orphan a citation (citations
// are separate rows keyed to the note). The component is deliberately self-contained so a
// ProseMirror/TipTap engine can replace the internals later behind the same imperative handle.
//
// The parent (NoteEditorPage) drives autosave and AI-assist; this component exposes an imperative
// handle (getSelection / replaceSelection / insert / focus) and reports selection changes so the
// assist menu can act on the highlighted text.

import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

export interface MarkdownEditorHandle {
  getSelection: () => { text: string; start: number; end: number };
  replaceSelection: (text: string) => void;
  insert: (text: string) => void;
  focus: () => void;
}

type Mode = "edit" | "split" | "preview";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSelectionChange?: (text: string) => void;
  readOnly?: boolean;
  mode?: Mode;
  onModeChange?: (m: Mode) => void;
  placeholder?: string;
}

// A toolbar action either wraps the selection (prefix/suffix) or inserts a line prefix.
interface ToolItem {
  icon: string;
  label: string;
  wrap?: [string, string];
  linePrefix?: string;
  block?: string;
}

const TOOLBAR: Array<ToolItem | "sep"> = [
  { icon: "H1", label: "Heading 1", linePrefix: "# " },
  { icon: "H2", label: "Heading 2", linePrefix: "## " },
  { icon: "H3", label: "Heading 3", linePrefix: "### " },
  "sep",
  { icon: "𝐁", label: "Bold", wrap: ["**", "**"] },
  { icon: "𝘐", label: "Italic", wrap: ["_", "_"] },
  { icon: "S̶", label: "Strikethrough", wrap: ["~~", "~~"] },
  { icon: "</>", label: "Inline code", wrap: ["`", "`"] },
  "sep",
  { icon: "•", label: "Bullet list", linePrefix: "- " },
  { icon: "1.", label: "Numbered list", linePrefix: "1. " },
  { icon: "☑", label: "Checklist", linePrefix: "- [ ] " },
  { icon: "❝", label: "Quote", linePrefix: "> " },
  "sep",
  { icon: "{ }", label: "Code block", block: "```\n\n```" },
  { icon: "▦", label: "Table", block: "| Column A | Column B |\n| --- | --- |\n| a | b |" },
  { icon: "🔗", label: "Link", wrap: ["[", "](https://)"] },
  { icon: "―", label: "Divider", block: "\n---\n" },
];

const MarkdownEditor = forwardRef<MarkdownEditorHandle, Props>(function MarkdownEditor(
  { value, onChange, onSelectionChange, readOnly = false, mode = "split", onModeChange, placeholder },
  ref,
) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const [internalMode, setInternalMode] = useState<Mode>(mode);
  const activeMode = onModeChange ? mode : internalMode;

  const setMode = useCallback(
    (m: Mode) => (onModeChange ? onModeChange(m) : setInternalMode(m)),
    [onModeChange],
  );

  const reportSelection = useCallback(() => {
    const ta = taRef.current;
    if (!ta || !onSelectionChange) return;
    onSelectionChange(value.slice(ta.selectionStart, ta.selectionEnd));
  }, [value, onSelectionChange]);

  useImperativeHandle(ref, () => ({
    getSelection() {
      const ta = taRef.current;
      if (!ta) return { text: "", start: 0, end: 0 };
      return { text: value.slice(ta.selectionStart, ta.selectionEnd), start: ta.selectionStart, end: ta.selectionEnd };
    },
    replaceSelection(text: string) {
      const ta = taRef.current;
      if (!ta) return;
      const { selectionStart: s, selectionEnd: e } = ta;
      const next = value.slice(0, s) + text + value.slice(e);
      onChange(next);
      requestAnimationFrame(() => {
        ta.focus();
        const pos = s + text.length;
        ta.setSelectionRange(pos, pos);
      });
    },
    insert(text: string) {
      const ta = taRef.current;
      const pos = ta ? ta.selectionStart : value.length;
      onChange(value.slice(0, pos) + text + value.slice(pos));
    },
    focus() {
      taRef.current?.focus();
    },
  }), [value, onChange]);

  function applyTool(item: ToolItem) {
    const ta = taRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = value.slice(start, end);
    let next = value;
    let caret = end;

    if (item.wrap) {
      const [pre, suf] = item.wrap;
      next = value.slice(0, start) + pre + selected + suf + value.slice(end);
      caret = start + pre.length + selected.length + suf.length;
    } else if (item.linePrefix) {
      // Prefix every line of the selection (or the current line).
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      const region = value.slice(lineStart, end || start);
      const prefixed = region
        .split("\n")
        .map((ln) => (ln.startsWith(item.linePrefix!) ? ln : item.linePrefix + ln))
        .join("\n");
      next = value.slice(0, lineStart) + prefixed + value.slice(end || start);
      caret = lineStart + prefixed.length;
    } else if (item.block) {
      const insert = (start > 0 && value[start - 1] !== "\n" ? "\n" : "") + item.block + "\n";
      next = value.slice(0, start) + insert + value.slice(start);
      caret = start + insert.length;
    }
    onChange(next);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(caret, caret);
    });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl/Cmd+B / I shortcuts.
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
      if (e.key === "b") { e.preventDefault(); applyTool({ icon: "", label: "", wrap: ["**", "**"] }); return; }
      if (e.key === "i") { e.preventDefault(); applyTool({ icon: "", label: "", wrap: ["_", "_"] }); return; }
    }
    // Tab inserts two spaces instead of leaving the field.
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart;
      onChange(value.slice(0, s) + "  " + value.slice(ta.selectionEnd));
      requestAnimationFrame(() => ta.setSelectionRange(s + 2, s + 2));
    }
  }

  const showEditor = activeMode !== "preview" && !readOnly;
  const showPreview = activeMode !== "edit" || readOnly;

  return (
    <div className={`note-editor mode-${readOnly ? "preview" : activeMode}`}>
      {!readOnly && (
        <div className="note-toolbar" role="toolbar" aria-label="Formatting">
          <div className="note-toolbar-tools">
            {TOOLBAR.map((item, i) =>
              item === "sep" ? (
                <span key={`s${i}`} className="note-toolbar-sep" aria-hidden="true" />
              ) : (
                <button
                  key={item.label}
                  type="button"
                  className="note-tool-btn"
                  title={item.label}
                  aria-label={item.label}
                  onClick={() => applyTool(item)}
                >
                  {item.icon}
                </button>
              ),
            )}
          </div>
          <div className="note-mode-switch" role="group" aria-label="View mode">
            {(["edit", "split", "preview"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={`note-mode-btn${activeMode === m ? " active" : ""}`}
                onClick={() => setMode(m)}
                title={`${m[0].toUpperCase()}${m.slice(1)} view`}
              >
                {m === "edit" ? "✏️" : m === "split" ? "⬌" : "👁"}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="note-editor-panes">
        {showEditor && (
          <textarea
            ref={taRef}
            className="note-source"
            value={value}
            spellCheck
            placeholder={placeholder || "Start writing your note in Markdown…"}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            onSelect={reportSelection}
            onMouseUp={reportSelection}
            onKeyUp={reportSelection}
          />
        )}
        {showPreview && (
          <div className="note-preview chat-markdown">
            {value.trim() ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                {value}
              </ReactMarkdown>
            ) : (
              <p className="note-preview-empty">Nothing to preview yet.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
});

export default MarkdownEditor;
