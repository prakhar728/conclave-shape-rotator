from __future__ import annotations
import hashlib
from difflib import SequenceMatcher

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from scipy.stats import rankdata

from config import settings
from skills.hackathon_novelty.models import HackathonSubmission

# Two project names with SequenceMatcher.ratio() at or above this threshold
# are flagged as a name collision. (A second check — substring containment
# of the shorter cleaned name in the longer — also flags as a collision and
# is what catches "FlowPay" inside "FlowPayments".)
NAME_COLLISION_THRESHOLD = 0.75

# A submission's best-fit track must score at least this similarity to be
# assigned. Below this, the submission is considered off-track and
# best_fit_track is None.
TRACK_MIN_SIMILARITY = 0.18

# Singleton — loads model once, reuses across calls
_model: SentenceTransformer | None = None
_model_load_failed = False
_FALLBACK_DIM = 256


def _get_model() -> SentenceTransformer | None:
    global _model, _model_load_failed
    if _model_load_failed:
        return None
    if _model is None:
        try:
            # Lazy import: sentence-transformers (→ torch) is OPTIONAL and not installed
            # in the deployed image — the core product embeds via nomic/Ollama. Absent
            # package raises ImportError here → caught below → graceful fallback.
            from sentence_transformers import SentenceTransformer

            # Keep the deterministic pipeline runnable in offline CI/local environments.
            _model = SentenceTransformer(settings.embedding_model, local_files_only=True)
        except Exception:
            _model_load_failed = True
            return None
    return _model


def _fallback_embeddings(texts: list[str]) -> np.ndarray:
    """Deterministic offline embedding fallback based on token hashing."""
    embeddings = np.zeros((len(texts), _FALLBACK_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        tokens = text.lower().split()
        if not tokens:
            tokens = [""]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % _FALLBACK_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            embeddings[row, index] += sign * weight

        norm = np.linalg.norm(embeddings[row])
        if norm > 0:
            embeddings[row] /= norm

    return embeddings


def fuse_text(submission: HackathonSubmission) -> str:
    """Idea text only — similarity/novelty based on core idea, not supporting materials."""
    return submission.idea_text


def compute_embeddings(texts: list[str]) -> np.ndarray:
    """Embed texts using sentence-transformers. Returns (N, D) array."""
    model = _get_model()
    if model is None:
        return _fallback_embeddings(texts)
    return model.encode(texts, show_progress_bar=False)


def pairwise_similarity(embeddings: np.ndarray) -> np.ndarray:
    """Compute (N, N) cosine similarity matrix."""
    return cosine_similarity(embeddings)


def compute_novelty_scores(sim_matrix: np.ndarray) -> np.ndarray:
    """Novelty = 1 - max(similarity to any OTHER submission). Diagonal masked."""
    masked = sim_matrix.copy()
    np.fill_diagonal(masked, -1.0)
    max_sim = masked.max(axis=1)
    novelty = 1.0 - max_sim
    return np.clip(novelty, 0.0, 1.0)


def compute_percentiles(novelty_scores: np.ndarray) -> np.ndarray:
    """Rank-based percentile. Higher novelty -> higher percentile."""
    ranks = rankdata(novelty_scores, method="average")
    n = len(novelty_scores)
    percentiles = (ranks / n) * 100.0
    return percentiles


def cluster_submissions(
    embeddings: np.ndarray,
    submissions: list[HackathonSubmission] | None = None,
) -> list[str]:
    """KMeans clustering. Auto-select k. Each cluster is labeled by the title
    of the submission closest to that cluster's centroid — gives readable
    names like 'FlowPay' or 'WeatherMesh' instead of 'Cluster_0'.
    """
    n = embeddings.shape[0]
    k = min(n, max(2, n // 3))
    if n < 2:
        return ["Uncategorized"] * n
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    if submissions is None or len(submissions) != n:
        # Fallback when submissions aren't provided (older callers / tests).
        label_names = [f"Cluster_{i}" for i in range(k)]
        return [label_names[l] for l in labels]

    centroids = kmeans.cluster_centers_
    label_names: list[str] = []
    for cluster_idx in range(k):
        member_idxs = [i for i, l in enumerate(labels) if l == cluster_idx]
        # Distance from each member to its centroid; pick the closest.
        diffs = embeddings[member_idxs] - centroids[cluster_idx]
        dists = np.linalg.norm(diffs, axis=1)
        rep_idx = member_idxs[int(np.argmin(dists))]
        rep_name = _project_name(submissions[rep_idx])
        label_names.append(rep_name or f"Cluster_{cluster_idx}")
    return [label_names[l] for l in labels]


def _project_name(submission: HackathonSubmission) -> str:
    """Best-effort title extraction.

    Handles three shapes idea_text can take:
    - Raw markdown:    "# FlowPay\n\nStreaming payments..."
    - Title-prefixed:  "FlowPay: Streaming payments..." (the ingest agent
      joins the markdown title to its description with ": " when it
      normalizes — see skills/hackathon_novelty/ingest.py).
    - Sentence-form:   "FlowPayHQ is a Solana program for recurring..."
      (what an agent skill produces when it summarizes a repo before
      submitting — there's no header or colon to anchor on).

    Strategy:
      1. Take the first non-empty line, strip leading markdown headers.
      2. If ": " appears within the first 40 chars, take the prefix.
      3. Else take leading capitalized words and stop at the first
         lowercase-starting word (caught common patterns like "X is/lets/
         provides Y"). Falls back to the full line if everything is
         capitalized.
    Capped at 80 chars.
    """
    text = (submission.idea_text or "").strip()
    if not text:
        return ""
    for line in text.split("\n"):
        cleaned = line.strip().lstrip("#").strip()
        if not cleaned:
            continue
        colon = cleaned.find(": ")
        if 0 < colon <= 40:
            return cleaned[:colon].strip()[:80]
        # Walk leading words; stop at first lowercase-starting token. This
        # collapses "FlowPayHQ is a Solana program..." -> "FlowPayHQ" but
        # keeps "Solar Trust" intact when no lowercase verb follows.
        words = cleaned.split()
        title_words: list[str] = []
        for w in words:
            if w and w[0].islower():
                break
            title_words.append(w)
        candidate = " ".join(title_words) if title_words else cleaned
        return candidate[:80]
    return ""


def compute_name_collisions(submissions: list[HackathonSubmission]) -> dict[str, list[dict]]:
    """For each submission, return any other submissions with similar project names.

    Uses difflib.SequenceMatcher (no external deps). O(N^2) — fine for hackathon-scale N.
    """
    names = [_project_name(s).lower() for s in submissions]
    out: dict[str, list[dict]] = {s.submission_id: [] for s in submissions}
    for i, a in enumerate(submissions):
        if not names[i]:
            continue
        for j, b in enumerate(submissions):
            if i == j or not names[j]:
                continue
            ratio = SequenceMatcher(None, names[i], names[j]).ratio()
            # Substring containment catches common-prefix collisions like
            # "FlowPay" inside "FlowPayments" that SequenceMatcher.ratio()
            # rates only ~0.74 because of length asymmetry. Min length 4 to
            # avoid trivial substrings like "Sol".
            short, long = sorted((names[i], names[j]), key=len)
            substring_hit = len(short) >= 4 and short in long
            if ratio >= NAME_COLLISION_THRESHOLD or substring_hit:
                # Score the substring case at the proportional overlap so
                # it's still informative, not a flat 1.0.
                sim = ratio if ratio >= NAME_COLLISION_THRESHOLD else len(short) / len(long)
                out[a.submission_id].append({
                    "other_submission_id": b.submission_id,
                    "similarity": round(float(sim), 3),
                })
    return out


def compute_track_alignments(
    submission_embeddings: np.ndarray,
    tracks: list[dict],
) -> tuple[list[dict[str, float]], list[str | None]]:
    """For each submission, score alignment against each track.

    Returns (per_submission_alignments, per_submission_best_fit). Track scores
    are cosine similarities clipped to [0, 1].
    """
    n = submission_embeddings.shape[0]
    if not tracks:
        return [{} for _ in range(n)], [None] * n

    # Embed only the track NAME, not the full markdown description. Long
    # markdown bodies share too many generic terms ("open-source", "Solana",
    # "tooling") and collapse the cosine-similarity discrimination — empirically
    # this drove ~13/20 submissions to "Public Goods & Open Source" because that
    # description was the most generically-worded.
    track_names = [t.get("name", f"track_{i}") for i, t in enumerate(tracks)]
    track_embeddings = compute_embeddings(track_names)
    sim = cosine_similarity(submission_embeddings, track_embeddings)
    sim = np.clip(sim, 0.0, 1.0)

    alignments: list[dict[str, float]] = []
    best_fit: list[str | None] = []
    for i in range(n):
        row = sim[i]
        alignments.append({track_names[j]: round(float(row[j]), 3) for j in range(len(tracks))})
        best_idx = int(np.argmax(row))
        best_fit.append(track_names[best_idx] if row[best_idx] >= TRACK_MIN_SIMILARITY else None)
    return alignments, best_fit


def run_deterministic(
    submissions: list[HackathonSubmission],
    guidelines: str = "",
    criteria: dict[str, float] | None = None,
    tracks: list[dict] | None = None,
) -> dict:
    """
    Full deterministic pipeline. Returns dict with:
    - embeddings: np.ndarray (N, D)
    - sim_matrix: np.ndarray (N, N)
    - novelty_scores: np.ndarray (N,)
    - percentiles: np.ndarray (N,)       — internal, used by triage_context
    - clusters: list[str] (N,)           — cluster label per submission
    - cluster_sizes: list[int] (N,)
    - submission_ids: list[str] (N,)
    - name_collisions: dict[submission_id -> list[{other_submission_id, similarity}]]
    - track_alignments: list[dict[track_name -> score]] (N,)
    - best_fit_tracks: list[str | None] (N,)
    """
    texts = [fuse_text(s) for s in submissions]
    embeddings = compute_embeddings(texts)
    sim_matrix = pairwise_similarity(embeddings)
    novelty_scores = compute_novelty_scores(sim_matrix)
    percentiles = compute_percentiles(novelty_scores)
    clusters = cluster_submissions(embeddings, submissions)
    cluster_sizes = [clusters.count(c) for c in clusters]
    name_collisions = compute_name_collisions(submissions)
    track_alignments, best_fit_tracks = compute_track_alignments(embeddings, tracks or [])

    return {
        "embeddings": embeddings,
        "sim_matrix": sim_matrix,
        "novelty_scores": novelty_scores,
        "percentiles": percentiles,
        "clusters": clusters,
        "cluster_sizes": cluster_sizes,
        "submission_ids": [s.submission_id for s in submissions],
        "name_collisions": name_collisions,
        "track_alignments": track_alignments,
        "best_fit_tracks": best_fit_tracks,
    }
