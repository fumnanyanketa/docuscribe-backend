# main.py — DocuScribe Backend
# Entry point for the FastAPI application

# dotenv loads the .env file so our API key is available
from dotenv import load_dotenv
load_dotenv()

# FastAPI is the web framework that handles all communication
from fastapi import FastAPI

# CORSMiddleware handles cross-origin requests
# This is what allows your React frontend on Vercel
# to talk to this backend on Render
from fastapi.middleware.cors import CORSMiddleware

# Create the FastAPI application instance
app = FastAPI(
    title="DocuScribe API",
    description="Document intelligence backend — by Fumnanya",
    version="1.0.0"
)

# Configure CORS — without this the browser blocks
# all communication between frontend and backend
app.add_middleware(
    CORSMiddleware,
    # In production this will be your Vercel URL
    # For now we allow all origins for testing
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
# This is a simple route that returns "ok"
# Render uses this to confirm your app is running
@app.get("/")
def health_check():
    return {
        "status": "ok",
        "app": "DocuScribe API",
        "version": "1.0.0",
        "by": "Fumnanya"
    }