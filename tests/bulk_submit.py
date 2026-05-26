"""
Bulk-submit mock hackathon ideas to a local Conclave enclave for end-to-end
testing.

For each `data/mock_ideas/idea_*/README.md` this script:
  1. POSTs /generate-token to mint a fresh participant token (one per idea —
     simulates 20 distinct participants).
  2. POSTs /submit with the README contents as `idea_text`. The repo
     directory name (e.g. `idea_03_flowpayments`) is used as a stub
     `repo_summary` so each submission has both fields populated.
  3. Logs (idea_dir, submission_id, token) to a JSONL so results can be
     fetched later, and so a single idea can be re-submitted as the same
     participant if needed.

Usage:
    python scripts/bulk_submit.py \\
        --base-url http://localhost:8000 \\
        --instance-id <uuid-from-/setup>

After the script finishes, run a manual evaluation:
    curl -X POST -H "Authorization: Bearer <admin-token>" \\
        http://localhost:8000/trigger

Then inspect results from the operator dashboard or via curl per logged
submission_id.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parent.parent
IDEAS_DIR = REPO_ROOT / "data" / "mock_ideas"
LOG_PATH = REPO_ROOT / "data" / "mock_ideas" / "submissions.jsonl"


def load_ideas() -> list[tuple[str, str]]:
    """Return [(idea_dir_name, readme_text)] for every idea_* folder."""
    out: list[tuple[str, str]] = []
    for d in sorted(IDEAS_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("idea_"):
            continue
        readme = d / "README.md"
        if not readme.exists():
            print(f"  ! skipping {d.name}: no README.md", file=sys.stderr)
            continue
        out.append((d.name, readme.read_text(encoding="utf-8")))
    return out


def submit_one(
    client: httpx.Client,
    base_url: str,
    instance_id: str,
    idea_dir: str,
    readme: str,
) -> dict:
    """Mint a fresh token and POST one submission. Returns log entry dict."""
    tok_resp = client.post(
        f"{base_url}/generate-token",
        json={"instance_id": instance_id},
        timeout=15,
    )
    tok_resp.raise_for_status()
    token = tok_resp.json()["token"]

    sub_resp = client.post(
        f"{base_url}/submit",
        json={
            "idea_text": readme,
            "repo_summary": f"Mock repo: {idea_dir}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    sub_resp.raise_for_status()
    body = sub_resp.json()

    return {
        "idea_dir": idea_dir,
        "submission_id": body["submission_id"],
        "token": token,
        "submissions_count": body.get("submissions_count"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--instance-id", required=True, help="instance UUID from POST /instances")
    ap.add_argument("--skip", default="", help="Comma-separated idea_dir names to skip (e.g. idea_20_conclaveself)")
    ap.add_argument("--limit", type=int, default=20, help="Submit only the first N ideas (sorted by directory name). Pass 0 for no limit.")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    ideas = [(d, r) for d, r in load_ideas() if d not in skip]
    if args.limit > 0:
        ideas = ideas[: args.limit]
    if not ideas:
        print("no ideas found under data/mock_ideas/", file=sys.stderr)
        return 1

    print(f"submitting {len(ideas)} ideas to {args.base_url} (instance {args.instance_id})")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client() as client, LOG_PATH.open("a", encoding="utf-8") as log:
        for idea_dir, readme in ideas:
            try:
                entry = submit_one(client, args.base_url, args.instance_id, idea_dir, readme)
            except httpx.HTTPStatusError as e:
                print(f"  ! {idea_dir}: HTTP {e.response.status_code}: {e.response.text}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"  ! {idea_dir}: {e}", file=sys.stderr)
                continue
            log.write(json.dumps(entry) + "\n")
            log.flush()
            print(f"  ok {idea_dir} -> {entry['submission_id'][:8]}... (cohort N={entry['submissions_count']})")

    print(f"\nlog written to {LOG_PATH}")
    print("next: trigger evaluation —")
    print(f"  curl -X POST -H 'Authorization: Bearer <admin-token>' {args.base_url}/trigger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
