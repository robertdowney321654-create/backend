"""Request and response schemas for workspace persistence."""

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ParticipantData(ApiModel):
    id: int
    name: str
    email: str
    track: str
    team: str


class TeamData(ApiModel):
    id: int
    name: str
    track: str
    members: int = Field(ge=0)
    stage: str


class SubmissionData(ApiModel):
    id: int
    title: str
    team: str
    track: str
    status: str
    score: int = Field(ge=0, le=100)
    votes: int = Field(ge=0)


class ScheduleItemData(ApiModel):
    date: str
    title: str
    detail: str


class EventData(ApiModel):
    id: str
    title: str
    host: str
    category: str
    format: str
    dates: str
    deadline: str
    registration_deadline: str = ""
    submission_deadline: str = ""
    voting_deadline: str = ""
    location: str
    description: str
    prize: str
    participants: int = Field(ge=0)
    spots: int = Field(ge=0)
    tracks: list[str] = Field(default_factory=list)
    eligibility: str = ""
    color: str = "mint"
    symbol: str = ""
    schedule: list[ScheduleItemData] = Field(default_factory=list)
    is_archived: bool = False


class RegistrationData(ApiModel):
    event_id: str
    name: str
    email: str
    track: str
    team_preference: str
    team_name: str = ""


class ProjectSubmissionData(ApiModel):
    id: int
    event_id: str
    title: str
    team: str
    track: str
    submitter_email: str = ""
    description: str = ""
    repository_url: str = ""
    demo_url: str = ""
    status: str = "Submitted"
    score: int = Field(default=0, ge=0, le=100)
    votes: int = Field(default=0, ge=0)


class RubricCriterionData(ApiModel):
    id: str
    label: str
    weight: int = Field(ge=0, le=100)


class JudgeScoreData(ApiModel):
    id: int
    event_id: str
    submission_id: int
    judge_email: str
    criterion_scores: dict[str, int]
    comment: str = ""


class WorkspaceData(ApiModel):
    events: list[EventData] = Field(default_factory=list)
    registrations: list[RegistrationData] = Field(default_factory=list)
    project_submissions: list[ProjectSubmissionData] = Field(default_factory=list)
    judging_rubric: list[RubricCriterionData] = Field(default_factory=list)
    judge_scores: list[JudgeScoreData] = Field(default_factory=list)
    published_event_ids: list[str] = Field(default_factory=list)
    participants: list[ParticipantData] = Field(default_factory=list)
    teams: list[TeamData] = Field(default_factory=list)
    submissions: list[SubmissionData] = Field(default_factory=list)
    judgingNormalized: bool = False
    resultsPublished: bool = False
    certificatesIssued: int = Field(default=0, ge=0)
    archived: bool = False