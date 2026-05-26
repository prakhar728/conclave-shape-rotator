import pytest
from pydantic import BaseModel
from core.skill_card import SkillCard
from skills.router import SkillRouter
from skills.hackathon_novelty import skill_card as hackathon_card
from skills.hackathon_novelty.models import HackathonSubmission
from skills.hackathon_novelty.config import ALLOWED_OUTPUT_KEYS, MIN_SUBMISSIONS


# --- SkillCard unit tests ---

class _DummyInput(BaseModel):
    submission_id: str
    value: int


def _make_dummy_card() -> SkillCard:
    return SkillCard(
        name="dummy",
        description="A test skill",
        run=lambda inputs, params: None,
        input_model=_DummyInput,
        output_keys={"submission_id", "score"},
        config={"threshold": 3},
        version="1.0.0",
    )


def test_skill_card_metadata_shape():
    card = _make_dummy_card()
    meta = card.metadata()
    assert meta["name"] == "dummy"
    assert meta["description"] == "A test skill"
    assert meta["version"] == "1.0.0"
    assert meta["output_keys"] == ["score", "submission_id"]   # sorted
    assert meta["config"] == {"threshold": 3}
    assert "input_schema" in meta                              # Pydantic JSON schema


def test_skill_card_input_schema_contains_fields():
    card = _make_dummy_card()
    schema = card.metadata()["input_schema"]
    props = schema.get("properties", {})
    assert "submission_id" in props
    assert "value" in props


def test_skill_card_config_defaults():
    card = SkillCard(
        name="minimal",
        description="",
        run=lambda: None,
        input_model=BaseModel,
        output_keys=set(),
    )
    assert card.config == {}
    assert card.version == "0.1.0"


# --- SkillRouter + SkillCard integration tests ---

def test_router_registers_skill_card():
    router = SkillRouter()
    card = _make_dummy_card()
    router.register(card)
    assert "dummy" in router.list_skills()


def test_router_list_cards_returns_metadata():
    router = SkillRouter()
    card = _make_dummy_card()
    router.register(card)
    cards = router.list_cards()
    assert len(cards) == 1
    assert cards[0]["name"] == "dummy"
    assert "input_schema" in cards[0]


def test_router_get_card():
    router = SkillRouter()
    card = _make_dummy_card()
    router.register(card)
    retrieved = router.get_card("dummy")
    assert retrieved.name == "dummy"


def test_router_get_card_missing_raises():
    router = SkillRouter()
    with pytest.raises(KeyError, match="not registered"):
        router.get_card("nonexistent")


def test_router_legacy_register_still_works():
    """Backward compat: register('name', callable) must still work."""
    router = SkillRouter()
    router.register("echo", lambda text: text)
    assert router.invoke("echo", text="hi") == "hi"


def test_router_legacy_appears_in_list_skills():
    router = SkillRouter()
    router.register("echo", lambda: None)
    assert "echo" in router.list_skills()


# --- hackathon_novelty SkillCard correctness ---

def test_hackathon_card_name():
    assert hackathon_card.name == "hackathon_novelty"


def test_hackathon_card_input_model():
    assert hackathon_card.input_model is HackathonSubmission


def test_hackathon_card_output_keys_match_config():
    assert hackathon_card.output_keys == ALLOWED_OUTPUT_KEYS


def test_hackathon_card_min_submissions_in_config():
    assert hackathon_card.config["min_submissions"] == MIN_SUBMISSIONS


def test_hackathon_card_input_schema_has_idea_text():
    schema = hackathon_card.metadata()["input_schema"]
    props = schema.get("properties", {})
    assert "idea_text" in props
    assert "submission_id" in props


def test_hackathon_card_run_is_callable():
    assert callable(hackathon_card.run)



# --- New fields: hackathon_novelty card tests ---

def test_hackathon_card_trigger_modes():
    modes = hackathon_card.trigger_modes
    assert len(modes) == 2
    mode_names = {m["mode"] for m in modes}
    assert mode_names == {"threshold", "manual"}


def test_hackathon_card_threshold_mode_default_config():
    threshold = next(m for m in hackathon_card.trigger_modes if m["mode"] == "threshold")
    assert "default_config" in threshold
    assert threshold["default_config"]["min_submissions"] == hackathon_card.config["min_submissions"]


def test_hackathon_card_roles():
    roles = hackathon_card.roles
    assert "admin" in roles
    assert "user" in roles
    assert "view_all_results" in roles["admin"]["capabilities"]
    assert roles["user"]["result_view"] == "own"
    assert "submit" in roles["user"]["capabilities"]


def test_hackathon_card_setup_prompt_nonempty():
    assert isinstance(hackathon_card.setup_prompt, str)
    assert len(hackathon_card.setup_prompt) > 0
