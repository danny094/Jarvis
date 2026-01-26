# adapters/Jarvis/persona_endpoints.py
"""
Persona Management API Endpoints

Provides REST API for managing AI personas:
- List all available personas
- Get specific persona content
- Upload new personas
- Switch active persona (hot-reload)
- Delete custom personas

Created: 2026-01-05
Phase 2 of Persona Management Feature
"""

import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

# Path setup for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.persona import (
    list_personas,
    load_persona,
    save_persona,
    delete_persona,
    switch_persona,
    get_active_persona_name,
    PERSONAS_DIR
)
from utils.logger import log_info, log_error, log_warn


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/api/personas",
    tags=["personas"],
    responses={
        404: {"description": "Persona not found"},
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"}
    }
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _validate_persona_name(name: str) -> bool:
    """
    Validate persona name.
    
    Rules:
    - No path traversal (../)
    - Alphanumeric, dash, underscore only
    - Not empty
    - Max 50 characters
    """
    if not name or len(name) > 50:
        return False
    
    # Block path traversal
    if ".." in name or "/" in name or "\\" in name:
        return False
    
    # Alphanumeric + dash + underscore only
    if not name.replace("-", "").replace("_", "").isalnum():
        return False
    
    return True


def _validate_persona_content(content: str) -> tuple[bool, Optional[str]]:
    """
    Validate persona file content.
    
    Returns: (is_valid, error_message)
    """
    # Size check (max 10KB)
    if len(content) > 10 * 1024:
        return False, "Content too large (max 10KB)"
    
    # Must contain [IDENTITY] section
    if "[IDENTITY]" not in content:
        return False, "Missing required [IDENTITY] section"
    
    # Must have a name
    if "name:" not in content.lower():
        return False, "Missing 'name' field in [IDENTITY]"
    
    return True, None


# ============================================================
# API ENDPOINTS (TO BE IMPLEMENTED)
# ============================================================

# Step 2: GET / - List all personas
# Step 3: GET /{name} - Get specific persona
# Step 4: POST / - Upload new persona
# Step 5: PUT /switch - Switch active persona
# Step 6: DELETE /{name} - Delete persona


# ============================================================
# STEP 2: GET / - List all personas
# ============================================================

@router.get("/")
async def get_all_personas() -> Dict[str, Any]:
    """
    List all available personas.
    
    Returns:
        {
            "personas": ["default", "dev", "creative", ...],
            "active": "default",
            "count": 3
        }
    
    Status Codes:
        200: Success
        500: Internal server error
    """
    try:
        personas = list_personas()
        active = get_active_persona_name()
        
        log_info(f"[PersonaAPI] Listed {len(personas)} personas, active: {active}")
        
        return {
            "personas": personas,
            "active": active,
            "count": len(personas)
        }
    
    except Exception as e:
        log_error(f"[PersonaAPI] Error listing personas: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list personas: {str(e)}"
        )


# ============================================================
# STEP 3: GET /{name} - Get specific persona
# ============================================================

@router.get("/{name}")
async def get_persona_by_name(name: str) -> Dict[str, Any]:
    """
    Get specific persona file content.
    
    Args:
        name: Persona name (without .txt extension)
    
    Returns:
        {
            "name": "default",
            "content": "...",
            "exists": true,
            "size": 1234,
            "active": false
        }
    
    Status Codes:
        200: Success
        400: Invalid persona name
        404: Persona not found
        500: Internal server error
    """
    # Validate name
    if not _validate_persona_name(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid persona name. Use alphanumeric, dash, underscore only."
        )
    
    try:
        # Check if file exists
        persona_file = PERSONAS_DIR / f"{name}.txt"
        
        if not persona_file.exists():
            log_warn(f"[PersonaAPI] Persona not found: {name}")
            raise HTTPException(
                status_code=404,
                detail=f"Persona '{name}' not found"
            )
        
        # Read content
        content = persona_file.read_text(encoding="utf-8")
        active = get_active_persona_name()
        
        log_info(f"[PersonaAPI] Retrieved persona: {name} ({len(content)} bytes)")
        
        return {
            "name": name,
            "content": content,
            "exists": True,
            "size": len(content),
            "active": (name == active)
        }
    
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    
    except Exception as e:
        log_error(f"[PersonaAPI] Error getting persona {name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get persona: {str(e)}"
        )


# ============================================================
# STEP 4: POST / - Upload new persona
# ============================================================

@router.post("/{name}")
async def upload_persona(name: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Upload new persona file.
    
    Accepts .txt file with persona configuration.
    Name is provided in URL path.
    
    Args:
        name: Persona name (from URL path)
        file: UploadFile (.txt file, max 10KB)
    
    Returns:
        {
            "success": true,
            "name": "my_persona",
            "size": 1234,
            "message": "Persona uploaded successfully"
        }
    
    Status Codes:
        200: Success
        400: Invalid file or content
        500: Internal server error
    """
    try:
        # Validate file extension
        if not file.filename.endswith('.txt'):
            raise HTTPException(
                status_code=400,
                detail="Only .txt files are allowed"
            )
        
        # Validate name (from URL parameter)
        if not _validate_persona_name(name):
            raise HTTPException(
                status_code=400,
                detail="Invalid persona name. Use alphanumeric, dash, underscore only."
            )
        
        # Read content
        content = await file.read()
        content_str = content.decode('utf-8')
        
        # Validate content
        is_valid, error_msg = _validate_persona_content(content_str)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid persona content: {error_msg}"
            )
        
        # Save persona
        success = save_persona(name, content_str)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to save persona file"
            )
        
        log_info(f"[PersonaAPI] Uploaded persona: {name} ({len(content_str)} bytes)")
        
        return {
            "success": True,
            "name": name,
            "size": len(content_str),
            "message": f"Persona '{name}' uploaded successfully"
        }
    
    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File must be valid UTF-8 text"
        )
    except Exception as e:
        log_error(f"[PersonaAPI] Upload error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during upload"
        )

@router.put("/{name}/switch")
async def switch_active_persona(name: str) -> Dict[str, Any]:
    """
    Switch to different persona (hot-reload).
    
    Args:
        name: Persona name to switch to (query parameter)
    
    Returns:
        {
            "success": true,
            "previous": "default",
            "current": "dev",
            "message": "Switched to 'dev'"
        }
    
    Status Codes:
        200: Success
        400: Invalid persona name
        404: Persona not found
        500: Internal server error
    """
    # Validate name
    if not _validate_persona_name(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid persona name"
        )
    
    try:
        # Check if persona exists
        persona_file = PERSONAS_DIR / f"{name}.txt"
        if not persona_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Persona '{name}' not found"
            )
        
        # Get previous active
        previous = get_active_persona_name()
        
        # Switch
        persona = switch_persona(name)
        
        log_info(f"[PersonaAPI] Switched persona: {previous} → {name}")
        
        return {
            "success": True,
            "previous": previous,
            "current": name,
            "message": f"Switched to '{name}'",
            "persona_name": persona.name  # Actual name from file
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        log_error(f"[PersonaAPI] Error switching persona: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to switch persona: {str(e)}"
        )


# ============================================================
# STEP 6: DELETE /{name} - Delete persona
# ============================================================

@router.delete("/{name}")
async def delete_persona_endpoint(name: str) -> Dict[str, Any]:
    """
    Delete custom persona.
    
    Protection: 
    - Cannot delete 'default' persona
    - Cannot delete currently active persona
    
    Args:
        name: Persona name to delete
    
    Returns:
        {
            "success": true,
            "deleted": "my_persona",
            "message": "Persona deleted successfully"
        }
    
    Status Codes:
        200: Success
        400: Invalid name, trying to delete 'default', or trying to delete active persona
        404: Persona not found
        500: Internal server error
    """
    # Validate name
    if not _validate_persona_name(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid persona name"
        )
    
    # Protect default persona
    if name == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete 'default' persona (protected)"
        )
    
    # Protect active persona
    current_active = get_active_persona_name()
    if name == current_active:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete active persona '{name}'. Switch to another persona first."
        )
    
    try:
        # Check if persona exists
        persona_file = PERSONAS_DIR / f"{name}.txt"
        if not persona_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Persona '{name}' not found"
            )
        
        # Delete
        success = delete_persona(name)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete persona"
            )
        
        log_info(f"[PersonaAPI] Deleted persona: {name}")
        
        return {
            "success": True,
            "deleted": name,
            "message": f"Persona '{name}' deleted successfully"
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        log_error(f"[PersonaAPI] Error deleting persona: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete persona: {str(e)}"
        )


# ============================================================
# END OF PERSONA ENDPOINTS
# ============================================================
