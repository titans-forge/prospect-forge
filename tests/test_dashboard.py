"""Dashboard tests: the server, its state API, and the review actions."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from prospect_forge import discovery, outreach, scoring
from prospect_forge.dashboard import PAGE, make_handler
from prospect_forge.store import Store

from test_prospect_forge import PROFILE_FIXTURE, SEED_FIXTURE


def _request(url: str, payload: dict | None = None) -> tuple[int, dict | str]:
    if payload is None:
        request = urllib.request.Request(url)
    else:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def _serve(tmp_path: Path, profiles: dict) -> tuple[ThreadingHTTPServer, str]:
    store = Store(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED_FIXTURE))
    discovery.import_seed(store, seed)
    scoring.score_all(store, profiles)
    outreach.plan_all(store, profiles)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, profiles))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_dashboard_serves_state_and_review_actions(tmp_path):
    profiles = {"test-profile": PROFILE_FIXTURE}
    server, base = _serve(tmp_path, profiles)
    try:
        # The page itself is the full self-contained document.
        status, page = _request(base + "/")
        assert status == 200 and "Prospect Forge" in page
        assert "nothing sends" in page.lower() or "never send" in page.lower()

        # State carries the funnel, the seeded prospects, and the one plan.
        status, state = _request(base + "/api/state")
        assert status == 200
        assert state["schema"] == "prospect_forge_dashboard_v1"
        assert state["funnel"]["total_prospects"] == 2
        assert state["funnel"]["plans_by_status"]["pending_review"] == 1
        assert state["profiles"]["test-profile"] == "Test product"
        plan_id = state["plans"][0]["plan_id"]
        assert state["plans"][0]["draft"]

        # The review gate: cannot mark sent before approval.
        status, error = _request(base + "/api/review",
                                 {"plan_id": plan_id, "decision": "sent"})
        assert status == 400 and "before review approval" in error["error"]

        # Approve, then send: prospect advances to contacted.
        status, ok = _request(base + "/api/review",
                              {"plan_id": plan_id, "decision": "approved"})
        assert status == 200 and ok["plan"]["status"] == "approved"
        status, ok = _request(base + "/api/review",
                              {"plan_id": plan_id, "decision": "sent"})
        assert status == 200 and ok["plan"]["status"] == "sent"
        _, state = _request(base + "/api/state")
        prospect = next(p for p in state["prospects"] if p["prospect_id"] == "pr-fixturehealth-example-com")
        assert prospect["status"] == "contacted"
    finally:
        server.shutdown()
        server.server_close()


def test_dashboard_rejects_bad_requests_and_unknown_paths(tmp_path):
    profiles = {"test-profile": PROFILE_FIXTURE}
    server, base = _serve(tmp_path, profiles)
    try:
        status, error = _request(base + "/api/review", {"plan_id": "nope", "decision": "approved"})
        assert status == 400 and "unknown plan" in error["error"]
        status, error = _request(base + "/api/review", {"plan_id": "x", "decision": "bogus"})
        assert status == 400
        status, _ = _request(base + "/missing")
        assert status == 404
        status, health = _request(base + "/api/health")
        assert status == 200 and health["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_dashboard_rescore_updates_state(tmp_path):
    profiles = {"test-profile": PROFILE_FIXTURE}
    server, base = _serve(tmp_path, profiles)
    try:
        status, ok = _request(base + "/api/score", {})
        assert status == 200 and ok["ok"] is True
        fit = ok["state"]["prospects"][0]["fit"]["test-profile"]
        assert fit["tier"] in ("warm", "hot", "cold")
    finally:
        server.shutdown()
        server.server_close()