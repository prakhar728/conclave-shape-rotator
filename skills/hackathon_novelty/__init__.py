"""
Entry point for the hackathon_novelty skill.

4-layer pipeline:
    0. ingest.py         — agentic text extraction + normalization (LLM)
    1. deterministic.py  — embeddings, similarity, novelty scores, clustering (no LLM)
    2. agent.py          — multi-node LangGraph graph (triage → router → flag/score → finalize)
    3. guardrails.py     — key whitelist, score clamping, leakage detection

What to edit here:
- run_skill(): change how triage_context is built (what signals the triage node receives)
- ALLOWED_OUTPUT_KEYS: add new output fields in config.py — this file doesn't need to change
- skill_card: update description or config if skill metadata changes

The skill_card is consumed by the SkillRouter and the /skills API endpoint.
Adding a field to NoveltyResult + ALLOWED_OUTPUT_KEYS is all that's needed to expose it in /results.
"""
from __future__ import annotations
from core.models import OperatorConfig, SkillResponse
from core.skill_card import SkillCard
from skills.hackathon_novelty.models import HackathonSubmission, NoveltyResult
from skills.hackathon_novelty.deterministic import run_deterministic
from skills.hackathon_novelty.ingest import run_ingest
from skills.hackathon_novelty.tools import set_context
from skills.hackathon_novelty.agent import run_agent
from skills.hackathon_novelty.guardrails import HackathonNoveltyFilter
from skills.hackathon_novelty.config import (
    ALLOWED_OUTPUT_KEYS,
    USER_OUTPUT_KEYS,
    MIN_SUBMISSIONS,
    SIMILARITY_DUPLICATE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
)


def run_skill(inputs: list[HackathonSubmission], params: OperatorConfig) -> SkillResponse:
    """Full 4-layer pipeline: ingest → deterministic → agent (multi-node graph) → guardrails → response.

    The pipeline runs at any cohort size; results are tagged confidence: "low" when
    the cohort is below LOW_CONFIDENCE_THRESHOLD so the agent skill can warn early
    submitters that scores will firm up as more submissions land.
    """
    if not inputs:
        return SkillResponse(skill="hackathon_novelty", results=[])

    confidence = "low" if len(inputs) < LOW_CONFIDENCE_THRESHOLD else "high"

    # Layer 0: Ingestion — normalize/extract text from any format
    normalized = run_ingest(inputs)
    for sub in inputs:
        if sub.submission_id in normalized:
            sub.idea_text = normalized[sub.submission_id]

    # Layer 1: Deterministic — embeddings, novelty, clustering, track alignment, name collisions
    det = run_deterministic(
        inputs,
        guidelines=params.guidelines,
        criteria=params.criteria,
        tracks=params.tracks,
    )

    # Build submissions map and set tool context
    submissions_map = {s.submission_id: s for s in inputs}
    set_context(det, submissions_map)

    # Build triage_context — rich signals the triage LLM uses to classify + judge relevance
    clusters = det["clusters"]
    sim_matrix = det["sim_matrix"]
    submission_ids = det["submission_ids"]

    # Pre-compute high-similarity pairs so triage LLM knows which to confirm as duplicates
    near_duplicate_pairs = []
    n = len(submission_ids)
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(sim_matrix[i, j])
            if sim >= SIMILARITY_DUPLICATE_THRESHOLD:
                near_duplicate_pairs.append((submission_ids[i], submission_ids[j], sim))

    triage_context = {}
    for i, sid in enumerate(submission_ids):
        triage_context[sid] = {
            "novelty_score": float(det["novelty_scores"][i]),
            "percentile": float(det["percentiles"][i]),
            "cluster": clusters[i],
            "cluster_size": clusters.count(clusters[i]),
            "idea_text": submissions_map[sid].idea_text,
            "near_duplicates": [
                {"other_id": a if b == sid else b, "similarity": round(sim, 3)}
                for a, b, sim in near_duplicate_pairs if sid in (a, b)
            ],
        }

    # Layer 2: Agent (multi-node graph)
    try:
        agent_results = run_agent(
            submission_ids=det["submission_ids"],
            criteria=params.criteria,
            guidelines=params.guidelines,
            triage_context=triage_context,
        )
    except Exception:
        # Keep the deterministic core usable when the online LLM path is
        # unavailable (e.g. offline CI, missing model endpoint, transient API
        # failure). Participants still get novelty / cluster / track outputs;
        # agent-derived fields fall back to neutral defaults.
        agent_results = [
            {
                "submission_id": sid,
                "criteria_scores": {c: 5.0 for c in params.criteria},
                "aligned": None,
                "status": "analyzed",
                "analysis_depth": "full",
                "duplicate_of": None,
            }
            for sid in det["submission_ids"]
        ]

    # Merge deterministic + agent results into NoveltyResult objects
    agent_map = {r["submission_id"]: r for r in agent_results}
    results = []
    for i, sid in enumerate(det["submission_ids"]):
        ar = agent_map.get(sid, {})
        result = NoveltyResult(
            submission_id=sid,
            novelty_score=float(det["novelty_scores"][i]),
            aligned=ar.get("aligned"),
            criteria_scores=ar.get("criteria_scores", {}),
            status=ar.get("status", "analyzed") if ar else "error",
            analysis_depth=ar.get("analysis_depth", "full"),
            duplicate_of=ar.get("duplicate_of", None),
            track_alignments=det["track_alignments"][i],
            best_fit_track=det["best_fit_tracks"][i],
            cluster_label=det["clusters"][i],
            cluster_size=det["cluster_sizes"][i],
            confidence=confidence,
            name_collisions=det["name_collisions"].get(sid, []),
        )
        results.append(result.model_dump())

    # Layer 3: Guardrails
    output_filter = HackathonNoveltyFilter()
    raw_inputs = [s.idea_text + (s.repo_summary or "") + (s.deck_text or "") for s in inputs]
    filtered_results = output_filter.apply(results, raw_inputs)

    return SkillResponse(skill="hackathon_novelty", results=filtered_results)


skill_card = SkillCard(
    name="hackathon_novelty",
    description=(
        "Scores hackathon submissions for novelty using agentic ingestion, embedding similarity, "
        "KMeans clustering, and a multi-node LangGraph agent (ingest → triage → score → guardrails). "
        "Raw submission content is accessible to the LLM inside the TEE; "
        "only derived outputs leave the pipeline."
    ),
    run=run_skill,
    input_model=HackathonSubmission,
    output_keys=ALLOWED_OUTPUT_KEYS,
    user_output_keys=USER_OUTPUT_KEYS,
    config={"min_submissions": MIN_SUBMISSIONS},
    trigger_modes=[
        {
            "mode": "threshold",
            "description": (
                "Pipeline auto-fires once the number of submissions reaches min_submissions. "
                "Re-runs on every subsequent submission so all scores stay current."
            ),
            "default_config": {"min_submissions": MIN_SUBMISSIONS},
            "admin_configurable": True,
        },
        {
            "mode": "manual",
            "description": (
                "Operator explicitly triggers a full evaluation run at any time, "
                "regardless of submission count."
            ),
        },
    ],
    roles={
        "admin": {
            "description": (
                "Hackathon director. Initialises the instance, sets evaluation criteria "
                "and guidelines, configures the submission threshold, and may trigger "
                "manual evaluation runs. Sees aggregated results for all submissions."
            ),
            "capabilities": ["configure", "trigger", "view_all_results"],
        },
        "user": {
            "description": (
                "Hackathon team. Submits idea text and optional supporting materials. "
                "Receives only their own novelty score and criteria breakdown — "
                "never sees other teams' submissions or scores."
            ),
            "capabilities": ["submit"],
            "result_view": "own",
        },
    },
    setup_prompt=(
        "This skill scores hackathon submissions for novelty and originality inside a TEE. "
        "No raw submission content ever leaves the enclave.\n\n"
        "As the admin, you need to provide:\n"
        "1. Evaluation criteria — a dict of criterion names to weights that sum to 1.0. "
        "Example: {\"originality\": 0.4, \"feasibility\": 0.3, \"impact\": 0.3}\n"
        "2. Guidelines — optional free-text instructions for the judging agent (e.g. 'Focus on AI/ML innovations').\n"
        "3. Trigger mode — choose 'threshold' (pipeline auto-runs once N submissions arrive) "
        "or 'manual' (you trigger evaluation yourself). Default threshold is 5 submissions, "
        "and you can override this.\n\n"
        "Users submit:\n"
        "- idea_text (required): A description of their hackathon idea.\n"
        "- repo_summary (optional): Technical details or a summary of their implementation.\n"
        "- deck_text (optional): Pitch deck or business case content.\n\n"
        "Each user receives: novelty_score (0-1, how unique your idea is compared to others) "
        "and an alignment flag (whether your idea fits the hackathon theme). "
        "They never see other teams' submissions or scores."
    ),
    user_display={
        "novelty_score":   {"type": "gauge",       "label": "Novelty",   "min": 0, "max": 1},
        "aligned":         {"type": "badge",       "label": "Aligned"},
        "criteria_scores": {"type": "score_table", "label": "Criteria Breakdown"},
    },
)
