"""Email/password and Google Identity account endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dogfood_seed import DOGFOOD_TOKENS
from app.models.account import Account, OrganizationProfile
from app.models.lifecycle import OrganizationMembership
from app.schemas.auth import (
    AccountCreate,
    AccountLogin,
    AccountView,
    OrganizationProfileUpdate,
    OrganizationProfileView,
    OrganizationMemberInvite,
    OrganizationMemberView,
    PersonProfileUpdate,
    SessionView,
)

router = APIRouter(prefix="/auth", tags=["auth"])
password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def _token_for(account: Account, active_role: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(account.id), "role": active_role, "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_db),
) -> Account:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    settings = get_settings()
    if settings.dogfood_mode:
        test_identity = next((identity for identity in DOGFOOD_TOKENS.values() if identity[0] == credentials.credentials), None)
        if test_identity is not None:
            _, email, active_role = test_identity
            account = await session.scalar(select(Account).where(Account.email == email))
            if account is None:
                raise HTTPException(status_code=401, detail="Dogfood fixture account is not seeded.")
            account.active_role = active_role
            if active_role == "organizer":
                account.active_workspace_owner_id = account.id
            return account
    try:
        claims = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        account_id = int(claims["sub"])
        active_role = str(claims["role"])
    except (JWTError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired.", headers={"WWW-Authenticate": "Bearer"}) from error
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.", headers={"WWW-Authenticate": "Bearer"})
    if active_role not in (account.roles or [account.role]):
        raise HTTPException(status_code=403, detail="This account no longer has access to that workspace.")
    account.active_role = active_role
    if active_role == "organizer":
        membership = await session.scalar(
            select(OrganizationMembership)
            .join(OrganizationProfile, OrganizationProfile.id == OrganizationMembership.organization_id)
            .where(OrganizationMembership.account_id == account.id)
            .order_by(OrganizationMembership.role.desc())
        )
        if membership is not None:
            organization = await session.get(OrganizationProfile, membership.organization_id)
            account.active_organization_id = membership.organization_id
            account.active_workspace_owner_id = organization.owner_id if organization else account.id
        else:
            account.active_workspace_owner_id = account.id
    return account


async def _session_view(account: Account, session: AsyncSession, active_role: str | None = None) -> SessionView:
    organization = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == account.id))
    if organization is None:
        membership = await session.scalar(
            select(OrganizationMembership)
            .join(OrganizationProfile, OrganizationProfile.id == OrganizationMembership.organization_id)
            .where(OrganizationMembership.account_id == account.id)
        )
        if membership is not None:
            organization = await session.get(OrganizationProfile, membership.organization_id)
    organization_view = OrganizationProfileView(
        name=organization.name,
        website=organization.website,
        description=organization.description,
    ) if organization else None
    active_role = active_role or account.role
    return SessionView(
        access_token=_token_for(account, active_role),
        account=AccountView(id=account.id, email=account.email, full_name=account.full_name, role=active_role, roles=account.roles or [account.role]),
        organization=organization_view,
    )


async def _create_account(
    email: str,
    full_name: str,
    role: str,
    encoded_password: str,
    organization_name: str,
    session: AsyncSession,
) -> Account:
    existing = await session.scalar(select(Account).where(Account.email == email.casefold()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.")
    if role == "organizer" and not organization_name.strip():
        raise HTTPException(status_code=422, detail="Organization name is required for organizers.")
    account = Account(email=email.casefold(), full_name=full_name.strip(), role=role, roles=[role], password_hash=encoded_password)
    session.add(account)
    await session.flush()
    if role == "organizer":
        session.add(OrganizationProfile(owner_id=account.id, name=organization_name.strip()))
    await session.commit()
    await session.refresh(account)
    if role == "organizer":
        organization = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == account.id))
        if organization is not None:
            session.add(OrganizationMembership(organization_id=organization.id, account_id=account.id, role="owner"))
            await session.commit()
    return account


@router.post("/register", response_model=SessionView, status_code=201)
async def register(payload: AccountCreate, session: AsyncSession = Depends(get_db)) -> SessionView:
    account = await _create_account(
        payload.email,
        payload.full_name,
        payload.role,
        password_hash.hash(payload.password),
        payload.organization_name,
        session,
    )
    return await _session_view(account, session, payload.role)


@router.post("/login", response_model=SessionView)
async def login(payload: AccountLogin, session: AsyncSession = Depends(get_db)) -> SessionView:
    account = await session.scalar(select(Account).where(Account.email == payload.email.casefold()))
    if account is None or not password_hash.verify(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    roles = list(account.roles or [account.role])
    if payload.role not in roles:
        if payload.role == "organizer":
            if not payload.organization_name.strip():
                raise HTTPException(status_code=422, detail="Enter an organization name to add organizer access.")
            organization = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == account.id))
            if organization is None:
                organization = OrganizationProfile(owner_id=account.id, name=payload.organization_name.strip())
                session.add(organization)
                await session.flush()
                session.add(OrganizationMembership(organization_id=organization.id, account_id=account.id, role="owner"))
        roles.append(payload.role)
        account.roles = roles
        await session.commit()
        await session.refresh(account)
    return await _session_view(account, session, payload.role)


@router.get("/me", response_model=SessionView)
async def current_session(account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> SessionView:
    return await _session_view(account, session, getattr(account, "active_role", account.role))


@router.put("/profile", response_model=AccountView)
async def update_person_profile(
    payload: PersonProfileUpdate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> AccountView:
    account.full_name = payload.full_name.strip()
    await session.commit()
    await session.refresh(account)
    return AccountView(id=account.id, email=account.email, full_name=account.full_name, role=getattr(account, "active_role", account.role), roles=account.roles or [account.role])


@router.get("/organization", response_model=OrganizationProfileView)
async def read_organization(account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> OrganizationProfileView:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organization profiles are only available to organizers.")
    profile = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == account.id))
    if profile is None:
        raise HTTPException(status_code=404, detail="Organization profile was not found.")
    return OrganizationProfileView(name=profile.name, website=profile.website, description=profile.description)


@router.put("/organization", response_model=OrganizationProfileView)
async def update_organization(
    payload: OrganizationProfileUpdate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> OrganizationProfileView:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organization profiles are only available to organizers.")
    profile = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == account.id))
    if profile is None:
        profile = OrganizationProfile(owner_id=account.id, name=payload.name)
        session.add(profile)
    profile.name = payload.name
    profile.website = str(payload.website) if payload.website else ""
    profile.description = payload.description
    await session.commit()
    return OrganizationProfileView(name=profile.name, website=profile.website, description=profile.description)


@router.get("/organization/members", response_model=list[OrganizationMemberView])
async def list_organization_members(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[OrganizationMemberView]:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required.")
    organization_id = getattr(account, "active_organization_id", None)
    if organization_id is None:
        raise HTTPException(status_code=404, detail="Organization profile was not found.")
    rows = (await session.execute(
        select(Account, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.account_id == Account.id)
        .where(OrganizationMembership.organization_id == organization_id)
    )).all()
    return [OrganizationMemberView(id=member.id, email=member.email, full_name=member.full_name, role=role) for member, role in rows]


@router.post("/organization/members", response_model=OrganizationMemberView, status_code=201)
async def invite_organization_member(
    payload: OrganizationMemberInvite,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> OrganizationMemberView:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required.")
    organization_id = getattr(account, "active_organization_id", None)
    membership = await session.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.account_id == account.id,
    ))
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only organization owners can invite members.")
    invited = await session.scalar(select(Account).where(Account.email == payload.email.casefold()))
    if invited is None:
        raise HTTPException(status_code=404, detail="That email does not have an account yet.")
    existing = await session.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.account_id == invited.id,
    ))
    if existing is None:
        session.add(OrganizationMembership(organization_id=organization_id, account_id=invited.id, role="member"))
    roles = list(invited.roles or [invited.role])
    if "organizer" not in roles:
        roles.append("organizer")
        invited.roles = roles
    await session.commit()
    return OrganizationMemberView(id=invited.id, email=invited.email, full_name=invited.full_name, role="member")
