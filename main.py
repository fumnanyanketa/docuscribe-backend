# main.py — DocuScribe Backend
# FastAPI application + MCP server in one file

import os
import uuid
from dotenv import load_dotenv
load_dotenv()

# ── Web framework imports ──────────────────────────────────────────
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Document processing imports ────────────────────────────────────
# pdfplumber extracts text from PDF files
import pdfplumber
# python-docx extracts text from Word documents
from docx import Document
import io

# ── MCP (Model Context Protocol) imports ──────────────────────────
# These come from the official Anthropic MCP Python SDK
from mcp.server.fastmcp import FastMCP

# ── Anthropic SDK import ───────────────────────────────────────────
import anthropic

# ── In-memory session store ────────────────────────────────────────
# A Python dictionary that holds extracted document text
# Key = session ID, Value = extracted text string
# This resets every time the server restarts (V1 only)
document_store = {}

# ── Create the FastAPI app ─────────────────────────────────────────
app = FastAPI(
    title="DocuScribe API",
    description="Document intelligence backend — by Fumnanya",
    version="1.0.0"
)

# ── Configure CORS ─────────────────────────────────────────────────
# Allows the React frontend on Vercel to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Create the MCP server ──────────────────────────────────────────
# FastMCP is the high-level MCP server class from the SDK
# This is the server Claude will connect to via URL
mcp = FastMCP("DocuScribe MCP Server")

# ── Session ID holder ──────────────────────────────────────────────
# Tracks which document is currently active
# In V1 only one document is active at a time
current_session_id = {"id": None}


# ══════════════════════════════════════════════════════════════════
# MCP RESOURCES
# Resources are data Claude can read — like opening a file
# ══════════════════════════════════════════════════════════════════

@mcp.resource("document://current")
def get_current_document() -> str:
    """
    Returns the full extracted text of the currently uploaded document.
    Claude reads this resource when it needs the document content.
    """
    session_id = current_session_id["id"]
    if not session_id or session_id not in document_store:
        return "No document currently loaded."
    return document_store[session_id]


# ══════════════════════════════════════════════════════════════════
# MCP TOOLS
# Tools are functions Claude can call to perform specific actions
# Each tool does exactly one job
# ══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_document_metadata() -> dict:
    """
    Returns basic metadata about the uploaded document.
    Use this to identify what type of document has been uploaded
    and get a high-level overview before deeper analysis.
    """
    session_id = current_session_id["id"]
    if not session_id or session_id not in document_store:
        return {"error": "No document currently loaded."}

    text = document_store[session_id]
    word_count = len(text.split())
    # Estimate reading time — average adult reads 200 words per minute
    reading_time_minutes = round(word_count / 200, 1)

    return {
        "word_count": word_count,
        "estimated_reading_time_minutes": reading_time_minutes,
        "character_count": len(text),
        "preview": text[:500] + "..." if len(text) > 500 else text
    }


@mcp.tool()
def get_document_summary() -> str:
    """
    Returns the full document text for Claude to summarise.
    Use this to generate a plain-language summary of the document.
    Claude should summarise in plain language avoiding legal jargon.
    Always note key parties, dates, and main obligations found.
    """
    session_id = current_session_id["id"]
    if not session_id or session_id not in document_store:
        return "No document currently loaded."
    # Return full text — Claude does the summarisation
    return document_store[session_id]


@mcp.tool()
def search_document(query: str) -> str:
    """
    Searches the document for content relevant to the user's query.
    Returns the most relevant sections of the document.
    Use this when the user asks a specific question about the document.
    Always cite which part of the document the answer comes from.
    """
    session_id = current_session_id["id"]
    if not session_id or session_id not in document_store:
        return "No document currently loaded."

    text = document_store[session_id]
    # Split document into paragraphs for searching
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

    # Find paragraphs containing query terms
    query_terms = query.lower().split()
    relevant = []

    for i, paragraph in enumerate(paragraphs):
        paragraph_lower = paragraph.lower()
        # Score each paragraph by how many query terms it contains
        score = sum(1 for term in query_terms if term in paragraph_lower)
        if score > 0:
            relevant.append((score, i, paragraph))

    # Sort by relevance score, return top 5 most relevant sections
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
    Extracts key structured information from the document.
    Returns parties involved, key obligations, dates, and risk flags.
    Use this to generate the one-page structured summary for the user.
    """
    session_id = current_session_id["id"]
    if not session_id or session_id not in document_store:
        return {"error": "No document currently loaded."}

    text = document_store[session_id]

    # Return the full text — Claude extracts the structured data
    # Claude is the reasoning layer, not this function
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


# ══════════════════════════════════════════════════════════════════
# MCP PROMPT
# Reusable prompt template that enforces consistent Claude behaviour
# ══════════════════════════════════════════════════════════════════

@mcp.prompt()
def legal_summary_prompt() -> str:
    """
    Standard prompt for legal document analysis.
    Enforces plain language, citation behaviour, and consistent output.
    """
    return """
    You are DocuScribe, a document intelligence assistant built by Fumnanya.
    
    Your job is to help non-lawyer professionals understand legal and 
    contractual documents clearly and quickly.
    
    Always follow these rules:
    1. Use plain language — no legal jargon unless you immediately explain it
    2. Always cite the specific section or clause your answer comes from
    3. Flag anything that appears unusual, risky, or requires legal advice
    4. Be direct and specific — the user needs to act on your answer
    5. Never invent information not found in the document
    """


# ══════════════════════════════════════════════════════════════════
# FASTAPI ROUTES
# HTTP endpoints the React frontend calls
# ══════════════════════════════════════════════════════════════════

@app.get("/")
def health_check():
    """Health check — confirms the backend is running."""
    return {
        "status": "ok",
        "app": "DocuScribe API",
        "version": "1.0.0",
        "by": "Fumnanya"
    }


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Receives an uploaded PDF or DOCX file from the frontend.
    Extracts the text, stores it in the session store.
    Returns a session ID the frontend uses for subsequent requests.
    """
    # Read the uploaded file into memory
    contents = await file.read()

    # Extract text based on file type
    extracted_text = ""

    if file.filename.endswith(".pdf"):
        # Use pdfplumber to extract text from PDF
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"

    elif file.filename.endswith(".docx"):
        # Use python-docx to extract text from Word document
        doc = Document(io.BytesIO(contents))
        for paragraph in doc.paragraphs:
            extracted_text += paragraph.text + "\n"

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a PDF or DOCX file."
        )

    # Check if extraction returned anything
    # This catches scanned PDFs that contain no readable text
    if len(extracted_text.strip()) < 100:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract readable text from this document. "
                "It may be a scanned image. "
                "Please upload a text-based PDF or Word document."
            )
        )

    # Generate a unique session ID for this upload
    session_id = str(uuid.uuid4())

    # Store the extracted text
    document_store[session_id] = extracted_text

    # Set this as the current active document
    current_session_id["id"] = session_id

    return {
        "session_id": session_id,
        "word_count": len(extracted_text.split()),
        "message": "Document uploaded and ready for analysis."
    }


class QuestionRequest(BaseModel):
    """Structure of a question request from the frontend."""
    question: str
    session_id: str


@app.post("/ask")
async def ask_question(request: QuestionRequest):
    """
    Receives a question from the frontend.
    Calls MCP tool functions directly to retrieve document content.
    Passes retrieved content to Claude for reasoning.
    Claude remains the reasoning layer — tools handle data access.
    """
    # Confirm the session exists
    if request.session_id not in document_store:
        raise HTTPException(
            status_code=404,
            detail="Session not found. Please upload a document first."
        )

    # Set the active session
    current_session_id["id"] = request.session_id

    # Call MCP tool functions directly to retrieve what Claude needs
    # This is equivalent to Claude calling these tools via remote URL
    # V2 will use full remote MCP server communication
    metadata = get_document_metadata()
    relevant_sections = search_document(request.question)

    # Build the context Claude will reason over
    # Claude receives structured tool output, not raw document text
    tool_context = f"""
DOCUMENT METADATA:
{metadata}

RELEVANT SECTIONS FOR THIS QUESTION:
{relevant_sections}
"""

    # Initialise the Anthropic client
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=60.0
    )

    # Call Claude with the tool output as context
    # Claude reasons over structured MCP tool output
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        system="""You are DocuScribe, a document intelligence assistant built by Fumnanya.

You have been given structured output from document analysis tools.
Use this information to answer the user's question clearly.

Always follow these rules:
1. Use plain language — no legal jargon unless you immediately explain it
2. Cite the specific section your answer comes from
3. Flag anything unusual, risky, or requiring legal advice
4. Be direct and specific — the user needs to act on your answer
5. Never invent information not found in the provided sections""",
        messages=[
            {
                "role": "user",
                "content": f"""Document analysis tool output:

{tool_context}

User question: {request.question}

Please answer the question based on the document sections provided above."""
            }
        ]
    )

    # Extract Claude's response
    answer = ""
    for block in response.content:
        if hasattr(block, "text"):
            answer += block.text

    return {
        "answer": answer,
        "session_id": request.session_id
    }


# ── Mount the MCP server onto FastAPI ─────────────────────────────
# This creates the /mcp endpoint Claude connects to
# Without this line the MCP server has no URL
app.mount("/mcp", mcp.streamable_http_app())