"""Versioned health endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report versioned API process health."""
    return {"status": "ok"}
