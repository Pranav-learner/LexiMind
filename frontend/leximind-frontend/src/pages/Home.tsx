import UploadPdf from "../components/UploadPdf";
import AskQuestion from "../components/AskQuestion";

export default function Home() {
  return (
    <div style={{ maxWidth: "800px", margin: "40px auto" }}>
      <h1>LexiMind</h1>
      <UploadPdf />
      <hr />
      <AskQuestion />
    </div>
  );
}
