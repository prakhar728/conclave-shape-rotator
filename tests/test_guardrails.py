import pytest
from core.guardrails import LeakageDetector, OutputFilterBase


# Concrete subclass for testing
class DummyFilter(OutputFilterBase):
    def check_bounds(self, result: dict) -> dict:
        return result


class TestLeakageDetector:
    def test_detects_substring(self):
        detector = LeakageDetector(min_length=20)
        raw = "This is a secret hackathon idea about blockchain voting"
        output = f"The submission discusses: {raw[:25]}"
        violations = detector.check(output, [raw])
        assert len(violations) > 0

    def test_no_false_positive_short_overlap(self):
        detector = LeakageDetector(min_length=20)
        raw = "My secret idea"  # too short to have 20-char substrings
        output = "Score: 0.85"
        violations = detector.check(output, [raw])
        assert len(violations) == 0

    def test_redact_replaces_leaked_text(self):
        detector = LeakageDetector(min_length=20)
        raw = "An AI-powered code review tool that detects vulnerabilities"
        output = f"Analysis: An AI-powered code review tool that detects vulnerabilities scored 0.8"
        redacted = detector.redact(output, [raw])
        assert "[REDACTED]" in redacted


class TestOutputFilterBase:
    def test_strips_disallowed_keys(self):
        f = DummyFilter(allowed_keys={"score", "id"})
        result = {"score": 0.8, "id": "1", "raw_idea": "secret", "internal_data": [1, 2, 3]}
        filtered = f.filter_keys(result)
        assert set(filtered.keys()) == {"score", "id"}

    def test_apply_full_pipeline(self):
        f = DummyFilter(allowed_keys={"score", "id"})
        results = [{"score": 0.8, "id": "1", "extra": "junk"}]
        filtered = f.apply(results, raw_inputs=["short"])
        assert "extra" not in filtered[0]
        assert filtered[0]["score"] == 0.8
