# LEXIMIND MASTER CONTEXT DOCUMENT

## PROJECT NAME

LexiMind

---

# PROJECT VISION

LexiMind is NOT a chatbot.

LexiMind is an Offline-First Multimodal Knowledge Operating System.

The long-term vision is:

* ingest any type of information
* understand relationships between information
* retrieve relevant context
* reason over retrieved knowledge
* answer grounded questions
* generate summaries
* generate notes
* generate flashcards
* create timelines
* compare sources
* build semantic memory
* support multimodal retrieval
* support agentic workflows
* operate fully offline or hybrid

The final goal is:

"ChatGPT for a user's private knowledge universe."

The system should behave like:

* NotebookLM
* Obsidian
* Perplexity
* ChatGPT
* Research Assistant

combined into a single knowledge platform.

---

# BUSINESS DIRECTION

LexiMind is NOT trying to compete with ChatGPT.

LexiMind is focused on:

AI Knowledge Workspace

Primary users:

* Students
* Researchers
* Knowledge Workers
* Privacy-focused users
* Universities
* Enterprises

Core differentiation:

* Offline-first
* Multimodal
* Grounded retrieval
* Semantic memory
* Cross-modal search
* Agent workflows

---

# ARCHITECTURAL DECISION

Chosen Architecture:

HYBRID / OFFLINE-FIRST

NOT Cloud-First SaaS.

Reason:

* Lower operating costs
* Privacy
* Data sovereignty
* Enterprise adoption
* Research workflows
* Student accessibility

Offline must always remain a first-class citizen.

Cloud components should be optional.

---

# CURRENT IMPLEMENTATION STATUS

Current LexiMind version already includes:

## Frontend

* React 19
* TypeScript
* Vite

Features:

* PDF upload
* Question input
* Citation display
* Answer rendering

---

## Backend

* FastAPI
* Uvicorn

Endpoints:

* /upload/pdf
* /query

---

## PDF Processing

Implemented:

* pdfplumber extraction
* heuristic cleaning
* header removal
* footer removal
* URL removal

---

## Chunking

Implemented:

* paragraph-aware chunking
* 80-250 word windows
* context-preserving segmentation

---

## Embeddings

Implemented:

SentenceTransformers

Model:

all-MiniLM-L6-v2

Output:

384-dimensional vectors

---

## Vector Store

Implemented:

FAISS IndexFlatL2

Files:

* vector_index.faiss
* vector_metadata.json

---

## Retrieval

Implemented:

semantic nearest-neighbor search

Current pipeline:

Question
→ Embedding
→ FAISS
→ Top K Chunks
→ LLM

---

## LLM

Implemented:

Ollama

Model:

Llama 3

Local inference only.

---

## Citations

Implemented:

* source filenames
* page numbers
* answer grounding

---

# CURRENT LIMITATIONS

Known limitations:

1. Dense retrieval only
2. No BM25
3. No reranking
4. No context orchestrator
5. No image understanding
6. No audio support
7. No multimodal embeddings
8. No memory system
9. No agents
10. No eval framework
11. No workspaces
12. No knowledge graph

---

# FINAL TARGET ARCHITECTURE

Input Layer
↓
Ingestion Layer
↓
Preprocessing Layer
↓
Multimodal Understanding
↓
Embedding Layer
↓
Vector Storage
↓
Retrieval Engine
↓
Reranking Engine
↓
Context Builder
↓
LLM Reasoning Layer
↓
Response Engine
↓
Memory Layer
↓
Agent Layer

---

# IMPORTANT ENGINEERING PRINCIPLES

Always prioritize:

1. Retrieval Quality
2. Context Engineering
3. Grounding
4. Source Attribution
5. Offline Capability

Never prioritize:

* flashy UI over retrieval quality
* large models over good retrieval
* more features over evaluation

---

# MULTI-AGENT STRATEGY

LexiMind WILL include agents.

However:

DO NOT build many agents initially.

Initial Agent Architecture:

Planner Agent
↓
Retriever Agent
↓
Verification Agent
↓
Response Agent

Later:

Summarization Agent

Timeline Agent

Flashcard Agent

Research Agent

Comparison Agent

---

# FIVE CORE AI ENGINEERING PILLARS

LexiMind must eventually include all five.

## 1. Multi-Agent Workflows

Status:
Future

Target:

Planner
Retriever
Verifier
Responder

---

## 2. Multimodal AI

Status:
Planned

Target Inputs:

* PDF
* Images
* Audio
* Video
* PPT
* DOCX
* Websites
* Code

---

## 3. Context Engineering

Status:
High Priority

Includes:

* token budgeting
* chunk selection
* deduplication
* context ranking
* context compression

---

## 4. Token Optimization

Status:
High Priority

Includes:

* prompt optimization
* chunk optimization
* retrieval filtering
* caching
* summarization

---

## 5. Evals

Status:
Mandatory

Every major feature must be measurable.

---

# DEVELOPMENT ROADMAP

Development phases replace the original 16 architecture phases.

The 16 architecture phases still exist conceptually but have been reorganized into practical engineering phases.

---

# PHASE 1

Production RAG Foundation

Goals:

* Hybrid Search
* BM25
* Better Chunking
* Metadata Filters
* Reranking
* Context Builder
* Streaming Ollama

Learn:

* Retrieval Engineering
* BM25
* Hybrid Search
* Reranking
* Context Engineering

Tech:

* rank-bm25
* CrossEncoder
* BGE Reranker

Priority:

CRITICAL

---

# PHASE 2

Product V1

Goals:

* Workspaces
* Library
* Notes
* Flashcards
* Citation Navigation
* Better UI

Learn:

* Product Design
* UX
* State Management

Tech:

* SQLite
* PDF.js
* Zustand

Priority:

CRITICAL

---

# PHASE 3

Image Intelligence

Goals:

* OCR
* Diagram Understanding
* Screenshot Understanding
* Scanned PDF Support

Learn:

* OCR
* Computer Vision
* Image Embeddings

Tech:

* PaddleOCR
* CLIP
* BLIP

Priority:

HIGH

---

# PHASE 4

Audio Intelligence

Goals:

* Lecture Processing
* Meeting Processing
* Voice Notes

Learn:

* Speech Recognition
* Audio Processing

Tech:

* Faster Whisper
* ffmpeg

Priority:

HIGH

---

# PHASE 5

Unified Multimodal Search

Goals:

* Cross-modal retrieval

Example:

Question
→ retrieve
text

* image
* audio

Learn:

* Embedding Spaces
* Multimodal Retrieval

Tech:

* CLIP
* ImageBind

Priority:

HIGH

---

# PHASE 6

Agent Workflow System

Goals:

* Planner Agent
* Retriever Agent
* Verification Agent

Learn:

* Multi-Agent Systems
* Tool Calling
* Orchestration

Priority:

HIGH

---

# PHASE 7

Memory & Knowledge Graph

Goals:

* Semantic Memory
* Entity Graphs
* Concept Linking

Learn:

* Knowledge Graphs
* Entity Extraction

Tech:

* Neo4j
* NetworkX

Priority:

HIGH

---

# PHASE 8

Evaluation Framework

Goals:

* Retrieval Evaluation
* Citation Evaluation
* Hallucination Evaluation

Metrics:

* Recall
* Precision
* Faithfulness
* Citation Accuracy
* Latency

Priority:

MANDATORY

---

# PHASE 9

Hybrid Infrastructure

Goals:

* Offline Mode
* Cloud Sync
* Security
* Scalability

Tech:

* Qdrant
* PostgreSQL
* Redis
* MinIO

Priority:

MEDIUM

---

# PHASE 10

Advanced Intelligence

Goals:

* Diagram QA
* Video Understanding
* Advanced Reasoning
* Autonomous Retrieval

Priority:

FUTURE

---

# LEARNING ROADMAP

Always learn only what the current phase requires.

Order:

1. Retrieval Engineering
2. Context Engineering
3. Local AI Systems
4. Multimodal AI
5. Agent Systems
6. Knowledge Graphs
7. Evals
8. Infrastructure

Never learn randomly.

Learning should directly support implementation.

---

# IMPORTANT RULES

1. Offline-first remains mandatory.
2. Retrieval quality is more important than model size.
3. Grounding is more important than fluent answers.
4. Evals are required before claiming improvements.
5. Build one phase completely before moving to the next.
6. Do not add features that do not improve the core knowledge workflow.
7. LexiMind is a Knowledge Operating System, not a chatbot.

END OF MASTER CONTEX