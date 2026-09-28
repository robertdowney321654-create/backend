"""Workspace API backed by normalized event records."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_account
from app.core.database import get_db
from app.models.account import Account
from app.schemas.workspace import WorkspaceData
from app.services.workspace_store import load_workspace, save_workspace

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceData)
async def read_workspace(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> WorkspaceData:
    """Return normalized records in the existing workspace response shape."""
    return await load_workspace(session, account)


@router.put("", response_model=WorkspaceData)
async def write_workspace(
    workspace: WorkspaceData,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> WorkspaceData:
    """Create or update the signed-in account's event records."""
    return await save_workspace(session, account, workspace)