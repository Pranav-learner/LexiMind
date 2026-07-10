// Drag & drop (or click-to-pick) uploader for PDFs. Uploads each file individually via
// uploadDocument (XHR) so every file gets its own progress bar, success/error state, and a
// Retry button. Non-PDF files are rejected client-side. Calls onUploaded() after each success
// so the parent list refreshes.

import { useCallback, useRef, useState } from "react";
import { uploadDocument } from "../../api/documents";

interface Props {
  workspaceId: string;
  onUploaded: () => void;
}

type UploadStatus = "uploading" | "success" | "error";

interface Upload {
  id: string;
  file: File;
  progress: number;
  status: UploadStatus;
  error: string | null;
}

let seq = 0;

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export default function UploadDropzone({ workspaceId, onUploaded }: Props) {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const patch = useCallback((id: string, next: Partial<Upload>) => {
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, ...next } : u)));
  }, []);

  const runUpload = useCallback(
    async (id: string, file: File) => {
      patch(id, { status: "uploading", progress: 0, error: null });
      try {
        const result = await uploadDocument(workspaceId, file, (pct) =>
          patch(id, { progress: pct }),
        );
        if (result.success) {
          patch(id, { status: "success", progress: 100 });
          onUploaded();
        } else {
          patch(id, { status: "error", error: result.error || "Upload failed." });
        }
      } catch (err) {
        patch(id, {
          status: "error",
          error: err instanceof Error ? err.message : "Upload failed.",
        });
      }
    },
    [workspaceId, onUploaded, patch],
  );

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const list = Array.from(files);
      for (const file of list) {
        const id = `u${++seq}`;
        if (!isPdf(file)) {
          setUploads((prev) => [
            ...prev,
            { id, file, progress: 0, status: "error", error: "Only PDF files are accepted." },
          ]);
          continue;
        }
        setUploads((prev) => [
          ...prev,
          { id, file, progress: 0, status: "uploading", error: null },
        ]);
        void runUpload(id, file);
      }
    },
    [runUpload],
  );

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }

  function retry(u: Upload) {
    if (!isPdf(u.file)) return;
    void runUpload(u.id, u.file);
  }

  return (
    <div className="doc-uploader">
      <div
        className={`doc-dropzone ${dragOver ? "dragover" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload PDFs"
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      >
        <span className="doc-dropzone-mark">⬆️</span>
        <p className="doc-dropzone-title">Drag &amp; drop PDFs here</p>
        <p className="doc-dropzone-sub">or click to browse — multiple files supported</p>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="doc-upload-list">
          {uploads.map((u) => (
            <li key={u.id} className={`doc-upload-item ${u.status}`}>
              <span className="doc-upload-name">{u.file.name}</span>
              <div className="doc-upload-body">
                {u.status === "uploading" && (
                  <div className="doc-progress">
                    <div className="doc-progress-bar" style={{ width: `${u.progress}%` }} />
                  </div>
                )}
                {u.status === "success" && <span className="doc-upload-ok">✓ Uploaded</span>}
                {u.status === "error" && (
                  <span className="doc-upload-err">✗ {u.error}</span>
                )}
              </div>
              {u.status === "error" && isPdf(u.file) && (
                <button className="ws-btn ghost doc-retry" onClick={() => retry(u)}>
                  Retry
                </button>
              )}
              {u.status === "uploading" && (
                <span className="doc-upload-pct">{u.progress}%</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
