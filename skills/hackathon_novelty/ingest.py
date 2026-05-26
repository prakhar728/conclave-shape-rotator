"""
Agentic ingestion node for hackathon_novelty.

Runs BEFORE the deterministic layer. Normalizes submission text from various
input formats (plain text, markdown, docx) and lengths (summarizes if > 300 words).

What makes it agentic:
- Short plain text → get_raw_text → done (1 tool call)
- Markdown file → parse_markdown → maybe summarize_text (1-2 tool calls)
- Docx file → extract_docx → maybe summarize_text (1-2 tool calls)
- Long text → get_raw_text → summarize_text (2 tool calls)
Different submissions take different tool-call paths in the same run.
"""
from __future__ import annotations
import json
import re

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from config import get_llm
from skills.hackathon_novelty.models import HackathonSubmission
from skills.hackathon_novelty.tools import INGEST_TOOLS, set_context
from skills.hackathon_novelty.config import INGEST_MODEL


INGEST_PROMPT_VERSION = "v1"

INGEST_SYSTEM_PROMPT = """You are an ingestion agent preparing hackathon submissions for evaluation.

For each submission, normalize the idea into clean, comparable plain text.

PROCESS (apply for each submission_id):
1. Check the submission's format:
   - If idea_file_type is "docx": call extract_docx
   - If idea_file_type is "markdown": call parse_markdown
   - If idea_file_type is null/text: call get_raw_text
2. Review the extracted text length:
   - If the text exceeds 300 words: call summarize_text to condense it
   - If under 300 words: use the extracted text as-is
3. Record the final normalized text for every submission

Output a JSON object mapping submission_id to normalized text:
{"sub_001": "normalized text...", "sub_002": "normalized text...", ...}

Include ALL submission_ids in your output.
"""


def run_ingest(submissions: list[HackathonSubmission]) -> dict[str, str]:
    """Run the agentic ingestion node. Returns {submission_id: normalized_text}.

    On any failure, returns {} so the caller can fall back to raw idea_text.
    """
    if not submissions:
        return {}

    try:
        # Set tool context (submissions map)
        submissions_map = {s.submission_id: s for s in submissions}
        # Build a minimal det dict just for the submissions map (no embeddings needed)
        set_context({"submission_ids": list(submissions_map.keys()), "sim_matrix": None}, submissions_map)

        llm = get_llm(INGEST_MODEL).bind_tools(INGEST_TOOLS)

        submission_list = ", ".join(
            f"{s.submission_id} (type={s.idea_file_type or 'text'})" for s in submissions
        )
        human_msg = f"Process these submissions: {submission_list}"
        messages = [SystemMessage(content=INGEST_SYSTEM_PROMPT), HumanMessage(content=human_msg)]

        # Tool loop — LLM calls tools, gets results, decides next action
        max_iterations = len(submissions) * 3 + 5
        iteration = 0
        response = None
        while iteration < max_iterations:
            response = llm.invoke(messages)
            messages.append(response)
            if not (hasattr(response, "tool_calls") and response.tool_calls):
                break
            tool_map = {t.name: t for t in INGEST_TOOLS}
            for tool_call in response.tool_calls:
                fn = tool_map.get(tool_call["name"])
                result = fn.invoke(tool_call["args"]) if fn else {"error": f"Unknown tool: {tool_call['name']}"}
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
            iteration += 1
    except Exception:
        return {}

    if response is None:
        return {}

    raw = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_ingest_output(raw, submissions)


def _parse_ingest_output(text: str, submissions: list[HackathonSubmission]) -> dict[str, str]:
    """Extract {submission_id: normalized_text} from LLM response.

    Only keeps IDs that exist in the submissions list.
    Returns {} if parsing fails.
    """
    valid_ids = {s.submission_id for s in submissions}
    result = {}

    try:
        # Bracket-match to find the JSON object
        match = re.search(r'\{', text)
        if match:
            start = match.start()
            depth = 0
            in_str = False
            escape = False
            end = -1
            for i in range(start, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_str:
                    escape = True
                    continue
                if c == '"':
                    in_str = not in_str
                if not in_str:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
            if end != -1:
                obj = json.loads(text[start:end])
                for sid, normalized in obj.items():
                    if sid in valid_ids and isinstance(normalized, str):
                        result[sid] = normalized
    except (json.JSONDecodeError, TypeError):
        pass

    return result
