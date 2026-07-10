// Modal for creating OR editing a workspace (name / description / icon / color) with inline
// client-side validation feedback. One component serves both the "Create" flow and the
// "Settings" flow to avoid duplicated form logic.

import { useEffect, useState } from "react";
import type { WorkspaceFormValues } from "../../types";
import { COLOR_PRESETS, ICON_PRESETS } from "./constants";

interface Props {
  mode: "create" | "edit";
  initial?: Partial<WorkspaceFormValues>;
  submitting?: boolean;
  serverError?: string | null;
  onSubmit: (values: WorkspaceFormValues) => void;
  onClose: () => void;
}

const NAME_MAX = 120;
const DESC_MAX = 2000;
const FORBIDDEN = /[/\\<>:"|?*]/;

export default function WorkspaceFormModal({
  mode,
  initial,
  submitting,
  serverError,
  onSubmit,
  onClose,
}: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [icon, setIcon] = useState(initial?.icon ?? ICON_PRESETS[0]);
  const [color, setColor] = useState(initial?.color ?? COLOR_PRESETS[0]);
  const [touched, setTouched] = useState(false);

  // Close on Escape for keyboard accessibility.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function nameError(): string | null {
    const trimmed = name.trim();
    if (!trimmed) return "Name is required.";
    if (trimmed.length > NAME_MAX) return `Name must be at most ${NAME_MAX} characters.`;
    if (FORBIDDEN.test(trimmed)) return 'Name cannot contain / \\ < > : " | ? *';
    return null;
  }

  const err = nameError();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (err) return;
    onSubmit({ name: name.trim(), description: description.trim(), icon, color });
  }

  return (
    <div className="ws-modal-overlay" onMouseDown={onClose}>
      <div
        className="ws-modal"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ws-modal-header">
          <h2>{mode === "create" ? "Create workspace" : "Workspace settings"}</h2>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={submit} className="ws-form">
          <div className="ws-preview" style={{ borderColor: color }}>
            <span className="ws-preview-icon" style={{ background: color }}>{icon}</span>
            <span className="ws-preview-name">{name.trim() || "Workspace name"}</span>
          </div>

          <label className="ws-field">
            <span>Name</span>
            <input
              autoFocus
              value={name}
              maxLength={NAME_MAX}
              placeholder="e.g. Operating Systems"
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setTouched(true)}
            />
            {touched && err && <small className="ws-error-text">{err}</small>}
          </label>

          <label className="ws-field">
            <span>Description <em>(optional)</em></span>
            <textarea
              rows={3}
              value={description}
              maxLength={DESC_MAX}
              placeholder="What lives in this workspace?"
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <div className="ws-field">
            <span>Icon</span>
            <div className="ws-picker">
              {ICON_PRESETS.map((p) => (
                <button
                  type="button"
                  key={p}
                  className={`ws-swatch ${icon === p ? "selected" : ""}`}
                  onClick={() => setIcon(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div className="ws-field">
            <span>Color</span>
            <div className="ws-picker">
              {COLOR_PRESETS.map((c) => (
                <button
                  type="button"
                  key={c}
                  className={`ws-color ${color === c ? "selected" : ""}`}
                  style={{ background: c }}
                  onClick={() => setColor(c)}
                  aria-label={c}
                />
              ))}
            </div>
          </div>

          {serverError && <div className="ws-error-banner">{serverError}</div>}

          <div className="ws-modal-actions">
            <button type="button" className="ws-btn ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="ws-btn primary" disabled={submitting || !!err}>
              {submitting ? "Saving…" : mode === "create" ? "Create" : "Save changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
