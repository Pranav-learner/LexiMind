type AnswerBoxProps = {
  answer: string;
};

type SourceItem = {
  document: string;
  page: string;
};

export default function AnswerBox({ answer }: AnswerBoxProps) {
  if (!answer) return null;

  const [answerText, sourcesRaw] = answer.split("Sources:");

  let sources: SourceItem[] = [];

  if (sourcesRaw) {
    sources = sourcesRaw
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.startsWith("-"))
      .map((line) => {
        // Example: "- AI_Roadmap.pdf (page 3)"
        const match = line.match(/- (.+) \(page (\d+)\)/);
        if (!match) return null;

        return {
          document: match[1],
          page: match[2],
        };
      })
      .filter(Boolean) as SourceItem[];
  }

  return (
    <div
      style={{
        marginTop: "20px",
        padding: "16px",
        border: "1px solid #ddd",
        borderRadius: "6px",
        backgroundColor: "#fafafa",
      }}
    >
      <h3>🧠 Answer</h3>

      <pre style={{ whiteSpace: "pre-wrap", lineHeight: "1.6" }}>
        {answerText.trim()}
      </pre>

      {sources.length > 0 && (
        <>
          <hr />
          <h4>📚 Sources</h4>

          <ul>
            {sources.map((src, index) => (
              <li key={index}>
                <strong>{src.document}</strong> — page {src.page}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
