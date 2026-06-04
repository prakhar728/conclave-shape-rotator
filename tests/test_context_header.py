"""Phase 3.5a C7 — context-header generator tests (fake LLM)."""
from __future__ import annotations

from transcripts.context_header import generate_header
from transcripts.llm import LLMUnavailable


class FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = self.text
        R.content = self.text
        return R()


class BrokenLLM:
    def invoke(self, messages):
        raise ConnectionError("ollama down")


def test_header_happy_path():
    llm = FakeLLM("Dstack salon session; Hang Yin demos CVM deployment.")
    out = generate_header("Hang Yin: you can deploy...", {"title": "Dstack Salon"}, llm=llm)
    assert out == "Dstack salon session; Hang Yin demos CVM deployment."
    # metadata made it into the prompt
    human = llm.calls[0][1].content
    assert "Dstack Salon" in human
    assert "<chunk>" in human


def test_header_whitespace_normalized():
    llm = FakeLLM("  Line one.\n\n  Line   two.  ")
    assert generate_header("x", llm=llm) == "Line one. Line two."


def test_header_truncated_at_word_boundary():
    llm = FakeLLM("word " * 200)
    out = generate_header("x", llm=llm, max_chars=50)
    assert len(out) <= 50
    assert not out.endswith(" ")
    assert "word" in out


def test_header_empty_on_provider_failure():
    assert generate_header("x", llm=BrokenLLM()) == ""


def test_header_empty_on_weird_response():
    class WeirdLLM:
        def invoke(self, messages):
            class R:
                content = ["not", "a", "string"]
            return R()
    out = generate_header("x", llm=WeirdLLM())
    # list gets stringified, not crash
    assert isinstance(out, str)
