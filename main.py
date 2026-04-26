# main.py — DocuScribe Backend
# FastAPI application + MCP server — by Fumnanya
# Version 2 — file-based session store for Render stability

import os
import uuid
import json
import io
from dotenv import load_dotenv
load_dotenv()

# ── Web framework ──────────────────────────────────────────────────
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Document processing ────────────────────────────────────────────
import pdfplumber
from docx import Document

# ── MCP server ─────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP

# ── Anthropic SDK ──────────────────────────────────────────────────
import anthropic


# ══════════════════════════════════════════════════════════════════
# SESSION STORE — FILE BASED
# Writes to /tmp/ on Render's disk so documents survive
# brief server restarts within a session
# ══════════════════════════════════════════════════════════════════

SESSIONS_FILE = "/tmp/docuscribe_sessions.json"


def load_sessions() -> dict:
    """Load all sessions from disk. Returns empty dict if none exist."""
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_sessions(sessions: dict):
    """Save all sessions to disk."""
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f)


def get_document_text(session_id: str) -> str:
    """Retrieve document text for a given session ID."""
    sessions = load_sessions()
    return sessions.get(session_id, "")


# Tracks which session is currently active
# Used by MCP tool functions to know which document to access
current_session_id = {"id": None}


# ══════════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="DocuScribe API",
    description="Document intelligence backend — by Fumnanya",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════
# MCP SERVER
# Claude connects to this via URL to access document tools
# ══════════════════════════════════════════════════════════════════

mcp = FastMCP("DocuScribe MCP Server")


# ── MCP RESOURCE ───────────────────────────────────────────────────

@mcp.resource("document://current")
def get_current_document() -> str:
    """
    Returns the full extracted text of the currently active document.
    Claude reads this when it needs the full document content.
    """
    session_id = current_session_id["id"]
    if not session_id:
        return "No document currently loaded."
    text = get_document_text(session_id)
    if not text:
        return "No document currently loaded."
    return text


# ── MCP TOOLS ──────────────────────────────────────────────────────

@mcp.tool()
def get_document_metadata() -> dict:
    """
    Returns basic metadata about the uploaded document.
    Use this to get a high-level overview before deeper analysis.
    """
    session_id = current_session_id["id"]
    if not session_id:
        return {"error": "No document currently loaded."}

    text = get_document_text(session_id)
    if not text:
        return {"error": "No document currently loaded."}

    word_count = len(text.split())
    reading_time = round(word_count / 200, 1)

    return {
        "word_count": word_count,
        "estimated_reading_time_minutes": reading_time,
        "character_count": len(text),
        "preview": text[:500] + "..." if len(text) > 500 else text
    }


@mcp.tool()
def get_document_summary() -> str:
    """
    Returns the full document text for Claude to summarise.
    Claude should summarise in plain language, noting key parties,
    dates, and main obligations. Avoid legal jargon.
    """
    session_id = current_session_id["id"]
    if not session_id:
        return "No document currently loaded."

    text = get_document_text(session_id)
    if not text:
        return "No document currently loaded."

    return text


@mcp.tool()
def search_document(query: str) -> str:
    """
    Searches the document for content relevant to the query.
    Returns the most relevant sections.
    Use this when the user asks a specific question.
    Always cite which section the answer comes from.
    """
    session_id = current_session_id["id"]
    if not session_id:
        return "No document currently loaded."

    text = get_document_text(session_id)
    if not text:
        return "No document currently loaded."

    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    query_terms = query.lower().split()
    relevant = []

    for i, paragraph in enumerate(paragraphs):
        paragraph_lower = paragraph.lower()
        score = sum(1 for term in query_terms if term in paragraph_lower)
        if score > 0:
            relevant.append((score, i, paragraph))

    relevant.sort(reverse=True)
    top_sections = relevant[:5]

    if not top_sections:
        return f"No sections found specifically mentioning: {query}"

    result = f"Most relevant sections for '{query}':\n\n"
    for score, idx, paragraph in top_sections:
        result += f"[Section {idx + 1}]: {paragraph}\n\n"

    return result


@mcp.tool()
def extract_structured_output() -> dict:
    """
    Returns the document text with instructions for structured extraction.
    Claude should extract parties, obligations, key dates, and risk flags.
    """
    session_id = current_session_id["id"]
    if not session_id:
        return {"error": "No document currently loaded."}

    text = get_document_text(session_id)
    if not text:
        return {"error": "No document currently loaded."}

    return {
        "document_text": text,
        "instruction": (
            "Extract and return: (1) all named parties, "
            "(2) key obligations for each party, "
            "(3) important dates and deadlines, "
            "(4) any clauses that appear unusual or high-risk. "
            "Format as a clean structured summary in plain English."
        )
    }


# ── MCP PROMPT ─────────────────────────────────────────────────────

@mcp.prompt()
def legal_summary_prompt() -> str:
    """Standard prompt enforcing plain language and citation behaviour."""
    return """
    You are DocuScribe, a document intelligence assistant built by Fumnanya.
    Help non-lawyer professionals understand legal and contractual documents.

    Rules:
    1. Use plain language — explain any legal terms you must use
    2. Always cite the specific section or clause your answer comes from
    3. Flag anything unusual, risky, or requiring legal advice
    4. Be direct and specific
    5. Never invent information not found in the document
    """


# ══════════════════════════════════════════════════════════════════
# FASTAPI ROUTES
# ══════════════════════════════════════════════════════════════════

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "app": "DocuScribe API",
        "version": "2.0.0",
        "by": "Fumnanya"
    }


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Receives a PDF or DOCX file.
    Extracts text and saves to disk-based session store.
    Returns session ID for subsequent requests.
    """
    contents = await file.read()
    extracted_text = ""

    if file.filename.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"

    elif file.filename.endswith(".docx"):
        doc = Document(io.BytesIO(contents))
        for paragraph in doc.paragraphs:
            extracted_text += paragraph.text + "\n"

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a PDF or DOCX file."
        )

    if len(extracted_text.strip()) < 100:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract readable text from this document. "
                "It may be a scanned image. "
                "Please upload a text-based PDF or Word document."
            )
        )

    # Generate session ID and save to disk
    session_id = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[session_id] = extracted_text
    save_sessions(sessions)

    # Set as current active session
    current_session_id["id"] = session_id

    return {
        "session_id": session_id,
        "word_count": len(extracted_text.split()),
        "message": "Document uploaded and ready for analysis."
    }


class QuestionRequest(BaseModel):
    question: str
    session_id: str


@app.post("/ask")
async def ask_question(request: QuestionRequest):
    """
    Receives a question and session ID.
    Calls MCP tool functions directly to retrieve document content.
    Passes structured tool output to Claude for reasoning.
    Claude is the reasoning layer — tools handle data access.
    """
    # Confirm session exists on disk
    sessions = load_sessions()
    if request.session_id not in sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found. Please upload a document first."
        )

    # Set active session for MCP tool functions
    current_session_id["id"] = request.session_id

    # Call MCP tool functions directly to get structured context
    metadata = get_document_metadata()
    relevant_sections = search_document(request.question)

    # Build structured context for Claude
    tool_context = f"""
DOCUMENT METADATA:
Word count: {metadata.get('word_count', 'unknown')}
Estimated reading time: {metadata.get('estimated_reading_time_minutes', 'unknown')} minutes
Preview: {metadata.get('preview', '')}

RELEVANT SECTIONS FOR THIS QUESTION:
{relevant_sections}
"""

    # Call Claude with structured MCP tool output
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=60.0
    )

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        system="""You are DocuScribe, a document intelligence assistant built by Fumnanya.
You have been given structured output from document analysis tools.
Use this to answer the user's question clearly.

Rules:
1. Plain language only — explain any legal terms
2. Cite the specific section your answer comes from
3. Flag anything unusual or requiring legal advice
4. Be direct — the user needs to act on your answer
5. Never invent information not in the provided sections""",
        messages=[
            {
                "role": "user",
                "content": f"""Document analysis tool output:

{tool_context}

User question: {request.question}

Answer based on the document sections above."""
            }
        ]
    )

    answer = ""
    for block in response.content:
        if hasattr(block, "text"):
            answer += block.text

    return {
        "answer": answer,
        "session_id": request.session_id
    }


# ── Mount MCP server ───────────────────────────────────────────────
app.mount("/mcp", mcp.streamable_http_app())