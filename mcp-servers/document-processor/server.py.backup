"""
Document Processor MCP Server
FastAPI-based MCP server compatible with Jarvis MCP Hub
"""

import os
import re
import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

# Import tool definitions
from tools import TOOLS

# ============================================================
# CONFIG
# ============================================================

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8087"))
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/tmp/trion/jarvis/workspace"))
DEFAULT_MAX_TOKENS = 4000
DEFAULT_OVERLAP_TOKENS = 200

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(title="Document Processor MCP Server")

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_session_path(conversation_id: str) -> Path:
    return WORKSPACE_ROOT / conversation_id

def ensure_session_dir(conversation_id: str) -> Path:
    session_path = get_session_path(conversation_id)
    session_path.mkdir(parents=True, exist_ok=True)
    (session_path / "chunks").mkdir(exist_ok=True)
    (session_path / "index").mkdir(exist_ok=True)
    return session_path

# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def handle_preprocess(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args["text"]
    add_paragraph_ids = args.get("add_paragraph_ids", True)
    normalize_whitespace = args.get("normalize_whitespace", True)
    remove_artifacts = args.get("remove_artifacts", True)
    
    original_length = len(text)
    cleaned = text
    removed = []
    
    if normalize_whitespace:
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r" {2,}", " ", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
    
    if remove_artifacts:
        page_pattern = r"Page \d+ of \d+"
        artifacts = re.findall(page_pattern, cleaned)
        removed.extend(artifacts)
        cleaned = re.sub(page_pattern, "", cleaned)
    
    id_map = {}
    if add_paragraph_ids:
        paragraphs = cleaned.split("\n\n")
        tagged = []
        for i, para in enumerate(paragraphs):
            if para.strip():
                para_id = f"[P{i+1:03d}]"
                id_map[para_id] = i
                tagged.append(f"{para_id} {para}")
            else:
                tagged.append(para)
        cleaned = "\n\n".join(tagged)
    
    return {
        "cleaned_text": cleaned,
        "id_map": id_map,
        "removed_artifacts": removed,
        "original_length": original_length,
        "cleaned_length": len(cleaned)
    }

def handle_analyze_structure(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args["text"]
    
    headings = []
    for match in re.finditer(r"^(#{1,3})\s+(.+)$", text, re.MULTILINE):
        level = len(match.group(1))
        headings.append({"level": level, "text": match.group(2).strip()})
    
    code_blocks = []
    for match in re.finditer(r"```(\w+)?\n(.*?)```", text, re.DOTALL):
        lang = match.group(1) or "unknown"
        code = match.group(2).strip()
        code_blocks.append({"language": lang, "lines": len(code.split("\n"))})
    
    keywords = list(set(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text)))[:20]
    lines = len(text.split("\n"))
    complexity = min(10, max(1, lines // 100))
    intro = text[:500] if len(text) > 500 else text
    
    return {
        "headings": headings,
        "code_blocks": code_blocks,
        "keywords": keywords,
        "intro": intro,
        "complexity": complexity,
        "has_tables": bool(re.search(r"\|.*\|", text)),
        "has_lists": bool(re.search(r"^[\*\-\+]\s", text, re.MULTILINE)),
        "total_lines": lines
    }

def handle_build_index(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args["text"]
    conversation_id = args["conversation_id"]
    
    session_path = ensure_session_dir(conversation_id)
    index_file = session_path / "index" / "index.json"
    
    words = re.findall(r"\b\w+\b", text.lower())
    word_freq = {}
    for word in words:
        if len(word) > 3:
            word_freq[word] = word_freq.get(word, 0) + 1
    
    top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:50]
    
    index_data = {
        "conversation_id": conversation_id,
        "created_at": datetime.datetime.now().isoformat(),
        "total_words": len(words),
        "unique_words": len(word_freq),
        "top_keywords": [{"word": w, "count": c} for w, c in top_keywords]
    }
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)
    
    return {"indexed": True, "index_path": str(index_file), **index_data}

def handle_chunk_document(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args["text"]
    conversation_id = args["conversation_id"]
    strategy = args.get("strategy", "semantic")
    max_tokens = args.get("max_tokens", DEFAULT_MAX_TOKENS)
    
    session_path = ensure_session_dir(conversation_id)
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_size = 0
    chunk_id = 1
    
    for para in paragraphs:
        para_size = len(para.split())
        
        if current_size + para_size > max_tokens and current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunk_file = session_path / "chunks" / f"{chunk_id:03d}.json"
            chunk_data = {
                "chunk_id": f"{chunk_id:03d}",
                "text": chunk_text,
                "tokens": current_size,
                "status": "pending",
                "created_at": datetime.datetime.now().isoformat()
            }
            with open(chunk_file, "w", encoding="utf-8") as f:
                json.dump(chunk_data, f, indent=2)
            
            chunks.append(chunk_data)
            current_chunk = []
            current_size = 0
            chunk_id += 1
        
        current_chunk.append(para)
        current_size += para_size
    
    if current_chunk:
        chunk_text = "\n\n".join(current_chunk)
        chunk_file = session_path / "chunks" / f"{chunk_id:03d}.json"
        chunk_data = {
            "chunk_id": f"{chunk_id:03d}",
            "text": chunk_text,
            "tokens": current_size,
            "status": "pending",
            "created_at": datetime.datetime.now().isoformat()
        }
        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(chunk_data, f, indent=2)
        chunks.append(chunk_data)
    
    return {
        "conversation_id": conversation_id,
        "total_chunks": len(chunks),
        "strategy": strategy,
        "chunks": [{"chunk_id": c["chunk_id"], "tokens": c["tokens"]} for c in chunks]
    }

def handle_get_session_status(args: Dict[str, Any]) -> Dict[str, Any]:
    conversation_id = args["conversation_id"]
    session_path = get_session_path(conversation_id)
    
    if not session_path.exists():
        return {"error": "Session not found", "conversation_id": conversation_id}
    
    chunks_dir = session_path / "chunks"
    chunks = list(chunks_dir.glob("*.json")) if chunks_dir.exists() else []
    
    chunk_statuses = {}
    for chunk_file in chunks:
        with open(chunk_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            chunk_statuses[data["chunk_id"]] = data.get("status", "unknown")
    
    return {
        "conversation_id": conversation_id,
        "total_chunks": len(chunks),
        "chunk_statuses": chunk_statuses,
        "session_path": str(session_path)
    }

def handle_cleanup_sessions(args: Dict[str, Any]) -> Dict[str, Any]:
    max_age_hours = args.get("max_age_hours", 24)
    dry_run = args.get("dry_run", True)
    
    if not WORKSPACE_ROOT.exists():
        return {"cleaned": 0, "dry_run": dry_run}
    
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=max_age_hours)
    cleaned = []
    
    for session_dir in WORKSPACE_ROOT.iterdir():
        if session_dir.is_dir():
            mtime = datetime.datetime.fromtimestamp(session_dir.stat().st_mtime)
            if mtime < cutoff:
                cleaned.append(session_dir.name)
                if not dry_run:
                    import shutil
                    shutil.rmtree(session_dir)
    
    return {"cleaned": len(cleaned), "dry_run": dry_run, "sessions": cleaned}

def handle_update_chunk_status(args: Dict[str, Any]) -> Dict[str, Any]:
    conversation_id = args["conversation_id"]
    chunk_id = args["chunk_id"]
    status = args["status"]
    summary = args.get("summary")
    error = args.get("error")
    
    session_path = get_session_path(conversation_id)
    chunk_file = session_path / "chunks" / f"{chunk_id}.json"
    
    if not chunk_file.exists():
        return {"error": f"Chunk {chunk_id} not found", "conversation_id": conversation_id}
    
    with open(chunk_file, "r", encoding="utf-8") as f:
        chunk_data = json.load(f)
    
    chunk_data["status"] = status
    
    if status == "done":
        chunk_data["completed_at"] = datetime.datetime.now().isoformat()
        if summary:
            chunk_data["summary"] = summary
    elif status == "failed":
        chunk_data["retry_count"] = chunk_data.get("retry_count", 0) + 1
        if error:
            chunk_data["error"] = error
    
    with open(chunk_file, "w", encoding="utf-8") as f:
        json.dump(chunk_data, f, indent=2)
    
    return chunk_data

# ============================================================
# MCP PROTOCOL ENDPOINTS
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "document-processor",
        "version": "2.0.0",
        "status": "healthy",
        "tools": len(TOOLS)
    }

@app.post("/mcp")
async def handle_mcp(request: Request):
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"tools": TOOLS}
        }
    
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            if tool_name == "preprocess":
                result = handle_preprocess(arguments)
            elif tool_name == "analyze_structure":
                result = handle_analyze_structure(arguments)
            elif tool_name == "build_index":
                result = handle_build_index(arguments)
            elif tool_name == "chunk_document":
                result = handle_chunk_document(arguments)
            elif tool_name == "get_session_status":
                result = handle_get_session_status(arguments)
            elif tool_name == "cleanup_sessions":
                result = handle_cleanup_sessions(arguments)
            elif tool_name == "update_chunk_status":
                result = handle_update_chunk_status(arguments)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                }
            
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}]
                }
            }
            
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32603, "message": str(e)}
            }
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    
    print(f"🚀 Document Processor MCP Server starting...")
    print(f"   Host: {HOST}:{PORT}")
    print(f"   Workspace: {WORKSPACE_ROOT}")
    print(f"   Tools: {len(TOOLS)}")
    
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
