const API_BASE = "http://127.0.0.1:8000";

export async function uploadPdf(file: File) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/upload/pdf`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error("PDF upload failed");
  }

  return response.json();
}

export async function askQuestion(question: string) {
  const response = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question }),
  });

  if (!response.ok) {
    throw new Error("Query failed");
  }

  return response.json();
}
