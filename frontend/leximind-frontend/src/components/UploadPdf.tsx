import { useState } from "react";
import { uploadPdf } from "../api/backend";

interface Props {
  // Phase 3: bind uploads to a workspace so chunks are indexed with its workspace_id.
  workspaceId?: string;
  onUploaded?: () => void;
}

export default function UploadPdf({ workspaceId, onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];

    if (!selected) return;

    // 🔒 Only allow PDFs
    if (selected.type !== "application/pdf") {
      setStatus("❌ Please upload a PDF file only");
      setFile(null);
      return;
    }

    setFile(selected);
    setStatus(`Selected: ${selected.name}`);
  }

  async function handleUpload() {
    if (!file) {
      setStatus("❌ No file selected");
      return;
    }

    try {
      setLoading(true);
      setStatus("⏳ Uploading and indexing PDF...");
      await uploadPdf(file, workspaceId);
      setStatus("✅ PDF uploaded and indexed successfully");
      setFile(null);
      onUploaded?.();
    } catch {
      setStatus("❌ Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ marginBottom: "30px" }}>
      <h3>📄 Upload PDF</h3>

      <input
        type="file"
        accept=".pdf"
        onChange={handleFileChange}
        disabled={loading}
      />

      <br />

      <button onClick={handleUpload} disabled={loading}>
        {loading ? "Uploading..." : "Upload"}
      </button>

      <p>{status}</p>
    </div>
  );
}
