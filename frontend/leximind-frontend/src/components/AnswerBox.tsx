type AnswerBoxProps = {
  answer: string;
  sources: string;
};

export default function AnswerBox({ answer, sources }: AnswerBoxProps) {
  if (!answer) return null;

  const sourceLines =
    sources
      ?.split("\n")
      .map((line) => line.trim())
      .filter((line) => line.startsWith("-")) || [];

  return (
    <div
      style={{
        marginTop: "20px",
        padding: "20px",
        border: "1px solid #ddd",
        borderRadius: "8px",
        backgroundColor: "#fafafa",
      }}
    >
      <h3 style={{ marginBottom: "10px" }}>🧠 Answer</h3>

      <div
        style={{
          whiteSpace: "pre-wrap",
          lineHeight: "1.7",
          fontSize: "15px",
        }}
      >
        {answer.trim()}
      </div>

      {/* {sourceLines.length > 0 && (
        <>
          <hr style={{ margin: "20px 0" }} />
          <h4>📚 Sources</h4>

          <ul>
            {sourceLines.map((line, index) => (
              <li key={index}>
                {line.replace("- ", "")}
              </li>
            ))}
          </ul>
        </>
      )} */}
    </div>
  );
}

