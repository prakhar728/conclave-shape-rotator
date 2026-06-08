"""QMSum -> normalized eval meetings (a translator "leaf").

QMSum (Zhong et al. 2021) is human-annotated query-based meeting
summarization over three domains:

    Academic  = ICSI research-group meetings
    Product   = AMI product-design meetings
    Committee  = Welsh/Canadian parliamentary committees

On disk each line of ``data/<Domain>/jsonl/<split>.jsonl`` is one meeting:

    {
      "meeting_transcripts": [{"speaker": str, "content": str}, ...],
      "specific_query_list": [{"query": str, "answer": str,
                                "relevant_text_span": [["start","end"], ...]}],
      "general_query_list":  [...],            # whole-meeting, no spans
      "topic_list": [...],
    }

We use ``specific_query_list`` only — those carry human-labelled
``relevant_text_span`` (inclusive, 0-based turn-index ranges into
``meeting_transcripts``), which become per-query gold ``relevant_turn_ids``.
Turn index == position in the segments list, so it lines up 1:1 with the
``turn_ids`` the chunker assigns after ingest.
"""
from __future__ import annotations

import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA = os.path.join(_REPO, "datasets", "qmsum", "data")

DOMAINS = ["Academic", "Committee", "Product"]
_TKEY = "meeting_transcripts"


def _spans_to_turn_ids(spans, n_turns: int) -> set[int]:
    out: set[int] = set()
    for pair in spans or []:
        a, b = int(pair[0]), int(pair[1])
        out.update(t for t in range(a, b + 1) if 0 <= t < n_turns)
    return out


def load(domain: str = "all", split: str = "test") -> list[tuple[dict, list[dict]]]:
    """Return ``[(meeting_norm, queries)]``.

    ``meeting_norm`` is the ingest-harness normalized form; ``queries`` is
    ``[{"q": str, "relevant_turn_ids": set[int]}]`` (only queries whose gold
    spans land inside the transcript are kept).
    """
    domains = DOMAINS if domain.lower() == "all" else [domain]
    out: list[tuple[dict, list[dict]]] = []
    for dom in domains:
        path = os.path.join(_DATA, dom, "jsonl", f"{split}.jsonl")
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                r = json.loads(line)
                segs = [
                    {"speaker": t["speaker"], "text": t["content"]}
                    for t in r[_TKEY]
                ]
                n = len(segs)
                queries = []
                for s in (r.get("specific_query_list") or []):
                    tids = _spans_to_turn_ids(s.get("relevant_text_span"), n)
                    if tids:
                        queries.append({"q": s["query"], "relevant_turn_ids": tids})
                meeting = {
                    "session_id": f"qmsum-{dom.lower()}-{split}-{i}",
                    "segments": segs,
                    "domain": dom,
                    "source": "qmsum",
                }
                out.append((meeting, queries))
    return out
