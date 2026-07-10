import { useState } from "react";
import { askQuestion } from "../api/backend";
import AnswerBox from "./AnswerBox";

interface Props {
  // Phase 3: scope the question to a single workspace's chunks.
  workspaceId?: string;
}

export default function AskQuestion({ workspaceId }: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleAsk() {
    if (!question.trim()) return;

    try {
      setLoading(true);
      setError("");
      setAnswer("");
      setSources("");

      const res = await askQuestion(question, workspaceId);

      setAnswer(res.answer || "");
      setSources(res.sources || "");

      setQuestion(""); // clear input
    } catch {
      setError("❌ Failed to fetch answer. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ marginTop: "30px" }}>
      <h3>❓ Ask a Question</h3>

      <textarea
        rows={3}
        value={question}
        placeholder="Ask something about the uploaded documents..."
        onChange={(e) => setQuestion(e.target.value)}
        style={{ width: "100%", padding: "8px" }}
        disabled={loading}
      />

      <br />

      <button
        onClick={handleAsk}
        disabled={loading || !question.trim()}
        style={{ marginTop: "10px" }}
      >
        {loading ? "Thinking..." : "Ask"}
      </button>


      {!answer && !loading && !error && (
        <p style={{ color: "#666", marginTop: "10px" }}>
          ℹ️ Upload a PDF and ask a question to get started.
        </p>
      )}


      {error && <p style={{ color: "red" }}>{error}</p>}

      {answer && (
        <AnswerBox
          answer={answer}
          sources={sources}
        />
      )}
    </div>
  );
}
