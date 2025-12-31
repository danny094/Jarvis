# Maintenance Endpoints für Memory Management
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

MEMORY_SERVICE_URL = "http://mcp-sql-memory:8081"

@router.get("/status")
async def get_maintenance_status():
    """Get current maintenance status."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{MEMORY_SERVICE_URL}/health", timeout=5.0)
            if response.status_code == 200:
                return {
                    "status": "ready",
                    "service": "online"
                }
    except Exception as e:
        return {
            "status": "error",
            "service": "offline",
            "error": str(e)
        }

@router.post("/start")
async def start_maintenance():
    """Start memory maintenance process."""
    try:
        async with httpx.AsyncClient() as client:
            # Call memory service maintenance endpoint
            response = await client.post(
                f"{MEMORY_SERVICE_URL}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "maintenance_run",
                        "arguments": {}
                    }
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "message": "Maintenance started"
                }
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Memory service returned {response.status_code}"
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Maintenance timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
