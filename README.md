# DocuScribe

**Document intelligence for non-lawyer professionals.**  
Upload any legal or contractual document. Ask plain-language questions. Get structured answers with source citations — in under five minutes.

**Live demo:** https://docuscribe-frontend.vercel.app  
**Built by:** Fumnanya Nketa

---

## The Problem

Professionals receive contracts, NDAs, service agreements, and legal documents regularly. Most do not have a lawyer on call to interpret them. Reading a 30-page document carefully takes time most people do not have. The result: documents get signed without being understood.

## What DocuScribe Does

- Upload a PDF or DOCX document
- Receive an automatic plain-language orientation — document type, key parties, estimated read time
- Ask any question in plain language
- Get answers that cite the specific clause or section they came from
- Generate a structured one-page summary: parties, obligations, key dates, risk flags

## Architecture

DocuScribe is a full-stack AI application built on a custom MCP (Model Context Protocol) server architecture.

React + Vite (Vercel)
│
▼
FastAPI Backend (Render)
├── Document processor — pdfplumber / python-docx
├── File-based session store — /tmp
├── MCP Server — Python MCP SDK
│   ├── Resource: document://current
│   ├── Tool: get_document_metadata()
│   ├── Tool: get_document_summary()
│   ├── Tool: search_document(query)
│   ├── Tool: extract_structured_output()
│   └── Prompt: legal_summary_prompt
└── Anthropic Claude API (reasoning layer)

**Architectural principle:** Claude is the reasoning layer only. Claude never receives raw document text directly. All document access is mediated through MCP tool functions. Claude receives structured tool output and reasons over it to produce plain-language answers.

## Key Design Decisions

**Why MCP?**  
Context stuffing — pasting full document text into Claude's prompt — breaks on large documents and gives Claude no structured way to navigate content. MCP gives Claude a standardised channel to retrieve only what it needs, when it needs it.

**Why FastAPI over Streamlit?**  
DocuScribe requires a proper REST API with file upload handling, session management, and a separately deployed frontend. Streamlit is purpose-built for data apps, not document intelligence systems with custom backends.

**Why file-based sessions?**  
Render's free tier spins down between requests. In-memory storage does not survive restarts. File-based sessions written to `/tmp` persist within a deployment cycle — sufficient for V1.

**Why four tools, not one?**  
Each MCP tool does exactly one job. This gives Claude precise, targeted access to document content rather than a sprawling tool that tries to do everything. Scoped tools produce more reliable, citation-grounded responses.

## Tech Stack

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | React 18 + Vite | Vercel |
| Backend | Python + FastAPI | Render |
| MCP Server | Python MCP SDK | Inside FastAPI |
| Document Processing | pdfplumber + python-docx | — |
| Session Storage | File-based (/tmp) | — |
| AI | Anthropic Claude Haiku | Anthropic API |

## Supported File Types

- PDF (text-based — not scanned images)
- DOCX (Microsoft Word)

## Running Locally

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
# Create .env with ANTHROPIC_API_KEY=your_key
uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
# Create .env with VITE_API_URL=http://127.0.0.1:8000
npm run dev
```

## Sprint Context

DocuScribe was built during Week 4 of the GodTier AI Architect Sprint — a 16-week learning sprint targeting the CCA-F (Claude Certified Architect — Foundations) certification.

**Exam connections:**
- Domain 2 (Tool Design and MCP Integration — 18%): custom MCP server, scoped tools, Claude as reasoning layer
- Domain 3 (Agent Architecture): session management, stateful document processing

**Skill-Pull Test:** This build pulled MCP server architecture from Week 9 of the sprint curriculum into Week 4.

---

*DocuScribe does not store documents permanently. Always seek qualified legal advice for important decisions.*