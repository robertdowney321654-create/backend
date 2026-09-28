"""Requests and responses for event lifecycle actions."""

from datetime import datetime

from pydantic import Field, HttpUrl

from app.schemas.workspace import ApiModel


class TeamCreate(ApiModel):
    event_id: str
    name: str = Field(min_length=2, max_length=120)
    track: str = Field(min_length=1, max_length=120)


class TeamView(ApiModel):
    id: int
    event_id: str
    name: str
    track: str
    members: int
    joined: bool
    invite_code: str = ""


class JudgeAssignmentCreate(ApiModel):
    email: str


class JudgeAssignmentView(ApiModel):
    event_id: str
    account_id: int
    email: str
    full_name: str


class EventJudgeView(ApiModel):
    account_id: int
    email: str
    full_name: str


class JudgeReview(ApiModel):
    event_id: str
    event_title: str
    event_tracks: list[str]
    submission_id: int
    submission_title: str
    submission_team: str
    track: str
    description: str
    rubric: list[dict[str, str | int]]
    score: dict[str, int]
    comment: str


class JudgeScoreSubmission(ApiModel):
    submission_id: int
    criterion_scores: dict[str, int]
    comment: str = Field(default="", max_length=4000)


class CommunityVoteCreate(ApiModel):
    submission_id: int


class ProjectCommentCreate(ApiModel):
    body: str = Field(min_length=1, max_length=2000)


class ProjectCommentView(ApiModel):
    id: int
    author: str
    body: str
    created_at: datetime


class EventWebhookCreate(ApiModel):
    target_url: HttpUrl
    event_types: list[str] = Field(min_length=1, max_length=8)


class EventWebhookView(ApiModel):
    id: int
    event_id: str
    target_url: str
    event_types: list[str]
    enabled: bool


class EventWebhookCreated(EventWebhookView):
    signing_secret: str


class CertificateVerificationView(ApiModel):
    valid: bool
    event_id: str
    event_title: str
    recipient_name: str
    issued_at: datetime
    verification_code: str


class CertificateView(ApiModel):
    event_id: str
    event_title: str
    recipient_name: str
    verification_code: str
    issued_at: datetime
