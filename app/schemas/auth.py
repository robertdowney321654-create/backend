"""Account, login, and profile request schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


class AccountCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    role: str = Field(pattern="^(participant|organizer|judge|admin)$")
    organization_name: str = Field(default="", max_length=180)


class AccountLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(pattern="^(participant|organizer|judge|admin)$")
    organization_name: str = Field(default="", max_length=180)


class PersonProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)


class AccountView(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    roles: list[str]


class OrganizationProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=180)
    website: HttpUrl | None = None
    description: str = Field(default="", max_length=2000)


class OrganizationProfileView(BaseModel):
    name: str
    website: str
    description: str


class OrganizationMemberInvite(BaseModel):
    email: EmailStr


class OrganizationMemberView(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


class SessionView(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account: AccountView
    organization: OrganizationProfileView | None = None
