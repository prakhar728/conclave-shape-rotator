"""C11 smoke gate — dashboard mounts cleanly + API still reachable.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G13 / §H C11:

- ``GET /dashboard/``                       → 200 + the shell HTML.
- ``GET /dashboard/app.js``                 → 200 + JS payload.
- ``GET /dashboard/styles.css``             → 200 + CSS payload.
- ``GET /dashboard/shape-ui/shape-canvas.js`` → 200 (vendored MIT).
- ``GET /dashboard/shape-ui/tokens.css``    → 200.
- ``GET /transcripts/sessions``             → 200 + JSON list (still wired).

"Looks flashy" is the manual visual check — that's a human-eyeball job,
not a unit assertion (§I last row of the test pyramid). What we *can*
mechanize is "every asset the page needs actually loads."
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Minimal app with the dashboard static mount + transcripts router.

    We don't import `main:app` itself because its module tree pulls in the
    interview_reflection MCP server (`mcp` Python package) which isn't
    installed in this env. The test's job is to verify the dashboard mount
    + API live happily side-by-side — that runs cleanly here without the
    unrelated import surface. The exact mount lines mirror what main.py uses.
    """
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from api.transcripts_routes import router as transcripts_router
    from storage import sqlite

    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()

    app = FastAPI()
    app.include_router(transcripts_router)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    app.mount("/dashboard", StaticFiles(directory=str(web_dir), html=True), name="dashboard")

    yield TestClient(app)
    monkeypatch.setattr(sqlite, "_conn", None)


def test_dashboard_shell_returns_html(client):
    r = client.get("/dashboard/")
    assert r.status_code == 200
    body = r.text
    # The shell loads the app.js module + the shape-ui tokens stylesheet.
    assert "<title>Conclave" in body
    assert "/dashboard/app.js" in body
    assert "/dashboard/shape-ui/tokens.css" in body


def test_dashboard_app_js_loads(client):
    r = client.get("/dashboard/app.js")
    assert r.status_code == 200
    # Spot-check that the file is the one we vendored, not a 404 HTML page.
    assert "mountShape" in r.text
    assert "/transcripts/sessions" in r.text


def test_dashboard_styles_css_loads(client):
    r = client.get("/dashboard/styles.css")
    assert r.status_code == 200
    assert ".card" in r.text


def test_shape_ui_assets_load(client):
    canvas = client.get("/dashboard/shape-ui/shape-canvas.js")
    tokens = client.get("/dashboard/shape-ui/tokens.css")
    notice = client.get("/dashboard/shape-ui/NOTICE.md")
    assert canvas.status_code == 200
    assert "mountShape" in canvas.text          # confirms it's the real file
    assert tokens.status_code == 200
    assert notice.status_code == 200
    assert "MIT" in notice.text                 # license notice preserved


def test_transcripts_api_still_reachable_alongside_dashboard(client):
    r = client.get("/transcripts/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
