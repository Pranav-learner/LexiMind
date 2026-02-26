import subprocess

def format_sources(chunks):
    sources = []
    seen = set()

    for chunk in chunks:
        key = (
            chunk["source"],
            chunk["page_number"],
            chunk.get("section_heading"),
            chunk.get("start_paragraph"),
            chunk.get("end_paragraph")
        )

        if key not in seen:
            seen.add(key)

            section = chunk.get("section_heading")
            score = chunk.get("score")
            start_para = chunk.get("start_paragraph")
            end_para = chunk.get("end_paragraph")

            # Format paragraph range
            if start_para == end_para:
                para_text = f"Paragraph {start_para}"
            else:
                para_text = f"Paragraphs {start_para}–{end_para}"

            if section:
                sources.append(
                    f"- {chunk['source']} | Page {chunk['page_number']} | {para_text} | Section: {section} | Score: {score}"
                )
            else:
                sources.append(
                    f"- {chunk['source']} | Page {chunk['page_number']} | {para_text} | Score: {score}"
                )

    return "\n".join(sources)


def generate_answer(question:str,chunks:list) -> str:
    """
    Generate an answer using retrieved chunks as context.
    """
    

    context = "\n\n".join(
        f"(Page {chunk['page_number']}): {chunk['text']}"
        for chunk in chunks
    )

    prompt  = f"""
    You are a precise question-answering assistant.

TASK:
Answer ONLY the question below.
Use ONLY the information present in the context.
DO NOT add extra explanations.
DO NOT include future topics or applications.
DO NOT infer beyond the context.

If the context does not explicitly contain the answer, say:
"I don't know based on the provided document."

FORMAT RULES:
- Answer in bullet points
- Maximum 5 bullet points
- Each bullet must be a prerequisite
- One line per bullet    

    Context:
    {context}

    Question:
    {question}

    Answer:
    """

    result = subprocess.run(
        ["ollama","run","llama3"],
        input = prompt.encode("utf-8"), # 🔑 force UTF-8 as ollama need is and  On Windows: Default encoding = cp1252
        #encode("utf-8") → converts Unicode text into bytes safely Ollama accepts UTF-8 bytes perfectly
        capture_output = True
    )

    answer_text =  result.stdout.decode("utf-8",errors="ignore").strip()

    # Build sources 
    sources_text = format_sources(chunks)


    final_answer = f"""
    Answer:
    {answer_text}

    Sources:
    {sources_text}
    """

    return final_answer


