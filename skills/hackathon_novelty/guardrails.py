"""
Output filter for the hackathon_novelty skill.

What to edit here:
- check_bounds(): add clamping logic for new numeric output fields
- String fields (status, analysis_depth, duplicate_of) pass through — no bounds needed
- To add a new numeric field: add a SCORE_BOUNDS entry in config.py and clamp it here

The guardrail pipeline (defined in core/guardrails.py) runs:
    filter_keys() → check_bounds() → leakage_check()

LeakageDetector is more important now that raw submission text flows through the LLM
in the analyze node. Even if the LLM includes submission content in its JSON response,
the detector catches and flags it before it reaches the API response.
"""
from core.guardrails import OutputFilterBase, LeakageDetector
from skills.hackathon_novelty.config import ALLOWED_OUTPUT_KEYS, SCORE_BOUNDS, MIN_LEAKAGE_SUBSTRING_LENGTH


class HackathonNoveltyFilter(OutputFilterBase):
    def __init__(self):
        super().__init__(
            allowed_keys=ALLOWED_OUTPUT_KEYS,
            leakage_detector=LeakageDetector(min_length=MIN_LEAKAGE_SUBSTRING_LENGTH),
        )

    def check_bounds(self, result: dict) -> dict:
        """Clamp numeric scores to valid ranges. String/bool fields pass through."""
        if "novelty_score" in result:
            lo, hi = SCORE_BOUNDS["novelty_score"]
            result["novelty_score"] = max(lo, min(hi, result["novelty_score"]))

        if "criteria_scores" in result and isinstance(result["criteria_scores"], dict):
            lo, hi = SCORE_BOUNDS["criteria_scores"]
            result["criteria_scores"] = {
                k: max(lo, min(hi, v))
                for k, v in result["criteria_scores"].items()
            }

        # aligned (bool), status, analysis_depth, duplicate_of are non-numeric — no bounds
        return result
