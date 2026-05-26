"""
S2 tests — collaboration profile + rubric panel Pydantic models.

Pure model validation (no LLM, no pipeline). Confirms the new models build from
representative dicts, carry the right defaults, and that NovelOutput accepts the
new fields while still accepting the legacy ones (back-compat this step).
"""
from __future__ import annotations

from skills.interview_reflection.models import (
    CollaborationProfile,
    NovelOutput,
    ProfileItem,
    RubricItem,
    RubricPanel,
    RubricScore,
)


def test_profile_item_defaults():
    item = ProfileItem(text="did contract audits")
    assert item.tags == []
    assert item.quote is None
    assert item.credibility is None


def test_collaboration_profile_from_dict():
    profile = CollaborationProfile(
        building="Solana consumer payments app",
        building_tags=["payments", "consumer-social", "crypto-protocol"],
        stage="early-traction",
        offers=[{
            "text": "two years of contract security audits",
            "tags": ["security-audit", "smart-contracts"],
            "quote": "I spent two years doing contract security audits",
            "credibility": "demonstrated",
        }],
        needs=[{
            "text": "token economics help",
            "tags": ["tokenomics", "defi"],
            "quote": "I'm stuck on our token economics",
        }],
    )
    assert profile.stage == "early-traction"
    assert profile.offers[0].credibility == "demonstrated"
    assert profile.needs[0].quote == "I'm stuck on our token economics"
    assert profile.interests == []
    assert profile.seeking == []


def test_collaboration_profile_empty_defaults():
    p = CollaborationProfile()
    assert p.building is None
    assert p.building_tags == []
    assert p.offers == [] and p.needs == [] and p.interests == []
    assert p.stage is None


def test_rubric_score_defaults_unreported():
    rs = RubricScore(rubric="coachability")
    assert rs.reported is False
    assert rs.score is None
    assert rs.band is None
    assert rs.items == []
    assert rs.contradiction_flag is None


def _panel() -> RubricPanel:
    def score(name: str) -> RubricScore:
        return RubricScore(
            rubric=name,
            score=4.0,
            band="strong",
            reported=True,
            items=[RubricItem(id="X1", score=4, quote="q")],
        )
    return RubricPanel(
        coachability=score("coachability"),
        agency=score("agency"),
        proactivity=score("proactivity"),
        goal_commitment=score("goal_commitment"),
        progress=score("progress"),
    )


def test_rubric_panel_has_five_rubrics():
    panel = _panel()
    assert panel.coachability.reported is True
    assert panel.progress.score == 4.0
    dumped = panel.model_dump()
    assert set(dumped.keys()) == {
        "coachability", "agency", "proactivity", "goal_commitment", "progress"
    }


def test_novel_output_accepts_new_fields_and_round_trips():
    out = NovelOutput(
        submission_id="s1",
        interviewee_slug="leo",
        collaboration_profile=CollaborationProfile(building="x", stage="idea"),
        rubric_panel=_panel(),
        rationale={"coachability": "Coachability: strong — ..."},
        summary="A short composed summary.",
        bullets=["✓ shipped the rewrite ('...')", "△ outbound slipping ('...')"],
    )
    dumped = out.model_dump()
    assert dumped["collaboration_profile"]["stage"] == "idea"
    assert dumped["rubric_panel"]["agency"]["reported"] is True
    assert dumped["rationale"]["coachability"].startswith("Coachability")
    assert dumped["summary"] == "A short composed summary."
    assert len(dumped["bullets"]) == 2
