"""Unversioned health route."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report application process health."""
    return {"status": "ok"}
