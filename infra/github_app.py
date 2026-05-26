"""
GitHub App integration — fetches repo summaries inside the TEE.

The private key is baked into the Docker image at CI time and never committed to git.
At runtime the enclave uses it to generate short-lived installation tokens.
"""

import base64
import os
import time
from pathlib import Path

import httpx
import jwt

PRIVATE_KEY_PATH = Path("/app/infra/github_app_private_key.pem")
GITHUB_API = "https://api.github.com"

# Max chars of README to include in the summary (keeps LLM context manageable)
README_LIMIT = 3000
# Max files to list from the repo tree
FILE_LIMIT = 50


def _get_jwt(app_id: str) -> str:
    """Generate a short-lived JWT for GitHub App authentication."""
    private_key = PRIVATE_KEY_PATH.read_text()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    return jwt.encode(payload, private_key, algorithm="RS256")


def _get_installation_token(app_id: str, installation_id: str) -> str:
    """Exchange a JWT for a short-lived installation access token (~1hr)."""
    token = _get_jwt(app_id)
    resp = httpx.post(
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def fetch_repo_summary(repo_url: str, app_id: str, installation_id: str) -> str:
    """
    Given a GitHub repo URL, fetch README + top-level file tree inside the TEE.
    Returns a plain-text summary suitable for HackathonSubmission.repo_summary.

    The installation token is used once and never stored.
    """
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse repo URL: {repo_url}")
    owner, repo = parts[-2], parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    token = _get_installation_token(app_id, installation_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    summary_parts = [f"Repository: {owner}/{repo}"]

    # README
    try:
        readme_resp = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/readme",
            headers=headers,
            timeout=15,
        )
        if readme_resp.status_code == 200:
            content = base64.b64decode(readme_resp.json()["content"]).decode(
                "utf-8", errors="replace"
            )
            summary_parts.append("README:\n" + content[:README_LIMIT])
    except Exception:
        pass

    # Top-level file tree
    try:
        tree_resp = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD",
            headers=headers,
            timeout=15,
        )
        if tree_resp.status_code == 200:
            files = [
                f["path"]
                for f in tree_resp.json().get("tree", [])
                if f["type"] == "blob"
            ]
            summary_parts.append("Files:\n" + "\n".join(files[:FILE_LIMIT]))
    except Exception:
        pass

    return "\n\n".join(summary_parts)


def fetch_public_repo_summary(repo_url: str) -> str:
    """
    Fetch README + file tree for a public repo without authentication.
    Used when the participant provides a public repo URL directly.
    """
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse repo URL: {repo_url}")
    owner, repo = parts[-2], parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    headers = {"Accept": "application/vnd.github+json"}
    summary_parts = [f"Repository: {owner}/{repo}"]

    try:
        readme_resp = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/readme",
            headers=headers,
            timeout=15,
        )
        if readme_resp.status_code == 200:
            content = base64.b64decode(readme_resp.json()["content"]).decode(
                "utf-8", errors="replace"
            )
            summary_parts.append("README:\n" + content[:README_LIMIT])
    except Exception:
        pass

    try:
        tree_resp = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD",
            headers=headers,
            timeout=15,
        )
        if tree_resp.status_code == 200:
            files = [
                f["path"]
                for f in tree_resp.json().get("tree", [])
                if f["type"] == "blob"
            ]
            summary_parts.append("Files:\n" + "\n".join(files[:FILE_LIMIT]))
    except Exception:
        pass

    return "\n\n".join(summary_parts)
