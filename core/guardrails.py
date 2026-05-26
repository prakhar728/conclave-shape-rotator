from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional


class LeakageDetector:
    """Detects if any raw input substring (>= min_length chars) appears in output."""

    def __init__(self, min_length: int = 20):
        self.min_length = min_length

    def check(self, output_text: str, raw_inputs: list[str]) -> list[str]:
        """Return list of leaked substrings found in output_text."""
        violations = []
        for raw in raw_inputs:
            for i in range(len(raw) - self.min_length + 1):
                substring = raw[i : i + self.min_length]
                if substring in output_text:
                    violations.append(substring)
                    break  # one violation per raw input is enough
        return violations

    def redact(self, output_text: str, raw_inputs: list[str]) -> str:
        """Replace leaked substrings with [REDACTED]."""
        for raw in raw_inputs:
            for i in range(len(raw) - self.min_length + 1):
                substring = raw[i : i + self.min_length]
                if substring in output_text:
                    output_text = output_text.replace(substring, "[REDACTED]")
        return output_text


class OutputFilterBase(ABC):
    """Abstract base class for skill-specific output filters."""

    def __init__(self, allowed_keys: set[str], leakage_detector: Optional[LeakageDetector] = None):
        self.allowed_keys = allowed_keys
        self.leakage_detector = leakage_detector or LeakageDetector()

    def filter_keys(self, result: dict) -> dict:
        """Strip any keys not in the whitelist."""
        return {k: v for k, v in result.items() if k in self.allowed_keys}

    @abstractmethod
    def check_bounds(self, result: dict) -> dict:
        """Clamp or reject out-of-bounds values. Skill-specific."""
        ...

    def apply(self, results: list[dict], raw_inputs: list[str]) -> list[dict]:
        """Full filter pipeline: keys -> bounds -> leakage check."""
        filtered = []
        for result in results:
            r = self.filter_keys(result)
            r = self.check_bounds(r)
            result_str = str(r)
            violations = self.leakage_detector.check(result_str, raw_inputs)
            if violations:
                r["_leakage_warning"] = f"Redacted {len(violations)} leaked substring(s)"
            filtered.append(r)
        return filtered
