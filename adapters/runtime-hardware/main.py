from fastapi import FastAPI

from runtime_hardware.api import router


app = FastAPI(
    title="Jarvis Runtime Hardware",
    version="0.1.0",
    description="Hardware inventory, capability, planning and validation service for Jarvis runtimes.",
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {
        "service": "jarvis-runtime-hardware",
        "status": "ok",
        "version": "0.1.0",
        "docs": "/docs",
    }
