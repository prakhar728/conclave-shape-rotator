from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class Submission(BaseModel):
    """Thin base — every skill input has at minimum a submission_id.
    Skills define their own subclass (e.g. HackathonSubmission) to add
    the fields they actually need.
    """
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Optional[dict] = None


class OperatorConfig(BaseModel):
    criteria: dict[str, float]  # e.g. {"originality": 0.4, "feasibility": 0.3, "impact": 0.3}
    guidelines: str = ""
    instance_id: str = "default"
    min_submissions: int = 5
    tracks: list[dict] = []  # [{name, description_markdown}] — phase 6 addition


class SkillRequest(BaseModel):
    skill_name: str
    inputs: list[dict]          # skill-specific input dicts, validated at invoke time
    params: OperatorConfig


class SkillResponse(BaseModel):
    skill: str
    results: list[dict]
    trace: Optional[list[dict]] = None
    enclave_signature: Optional[str] = None   # added by infra side
    attestation_quote: Optional[str] = None   # added by infra side


class TrackConfig(BaseModel):
    """One track in a hackathon — name + markdown description used by the
    track-alignment scoring layer (added in phase 6)."""
    name: str
    description_markdown: str


class CreateInstanceRequest(BaseModel):
    """Typed operator setup payload for POST /instances."""
    name: str  # hackathon display name (e.g. "Frontier 2026")
    end_date: datetime
    evaluation_frequency: str  # e.g. "1w", "3d", "12h", "30m"
    tracks: list[TrackConfig] = Field(min_length=1)


class CreateInstanceResponse(BaseModel):
    instance_id: str
    admin_token: str
    enclave_url: str


class CreateInterviewInstanceRequest(BaseModel):
    """Operator setup payload for POST /instances/interview.

    Slimmer than CreateInstanceRequest because interview_reflection has no
    tracks and no criteria (the skill produces themes + ownership prompts,
    not weighted scores). end_date is optional — interview cohorts are
    ongoing rather than time-bounded like hackathons.
    """
    name: str                              # cohort display name (e.g. "Shape Rotator Spring 2026")
    end_date: Optional[datetime] = None    # optional; defaults to 1 year ahead
    evaluation_frequency: str = "1d"       # kept for scheduler compat; pipeline runs per-submit
