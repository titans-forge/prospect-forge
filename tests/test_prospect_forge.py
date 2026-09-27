"""Tests for Prospect Forge: the full funnel, fixtures only, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospect_forge import discovery, outreach, report, research, scoring
from prospect_forge.discovery import parse_feed
from prospect_forge.icp import load_profiles, validate_profile
from prospect_forge.store import Store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"

PROFILE_FIXTURE = {
    "schema": "prospect_forge_icp_v1",
    "profile_id": "test-profile",
    "product_name": "Test product",
    "value_prop": "does the thing",
    "proof_points": ["proof one"],
    "industries": ["healthtech"],
    "size_bands": [{"min": 10, "max": 5000}],
    "signals": [
        {"id": "llm", "weight": 3, "description": "ships an LLM",
         "keywords": ["AI assistant"]},
        {"id": "funding", "weight": 2, "description": "recently raised",
         "keywords": ["Series A"]},
        {"id": "regulatory", "weight": 4, "description": "regulatory pressure",
         "keywords": ["FTC"]},
    ],
    "approach_roles": ["Chief Compliance Officer", "Chief Medical Officer"],
    "channels": [{"id": "direct_email", "label": "email"}],
    "default_channel": "direct_email",
    "angles": [
        {"id": "reg-angle", "signal_ids": ["regulatory"],
         "subject": "Grounding for {company}",
         "template": "Hi {company} — {signal_evidence}. {value_prop}. {proof_point}."},
        {"id": "llm-angle", "signal_ids": ["llm"],
         "subject": "Audits for {company}",
         "approach_role": "Chief Medical Officer",
         "template": "Hi {company} — {signal_evidence}. {value_prop}. {proof_point}."},
        {"id": "default", "signal_ids": [],
         "subject": "Idea for {company}",
         "template": "Hi {company} — {signal_evidence}. {value_prop}. {proof_point}."},
    ],
}

SEED_FIXTURE = {
    "schema": "prospect_forge_seed_v1",
    "profile_id": "test-profile",
    "companies": [
        {"name": "Fixture Health", "domain": "fixturehealth.example.com",
         "industry": "healthtech",
         "signals": [{"id": "llm", "evidence": "ships an AI assistant",
                      "source_url": "https://fixturehealth.example.com"},
                     {"id": "regulatory", "evidence": "named in an FTC action",
                      "source_url": "https://fixturehealth.example.com/news"}]},
        {"name": "Wrong Industry Co", "domain": "wrongindustry.example.com",
         "industry": "agritech", "signals": []},
    ],
}


# ── ICP validation ────────────────────────────────────────────────────────


def test_committed_profiles_are_valid():
    profiles = load_profiles(PROFILES_DIR)
    assert set(profiles) >= {"health-grounding", "diagnostic-trainer"}


def test_profile_validation_rejects_unknown_template_slot():
    profile = json.loads(json.dumps(PROFILE_FIXTURE))
    profile["angles"][0]["template"] = "{company} uses {bogus_slot}"
    with pytest.raises(ValueError, match="unknown slots"):
        validate_profile(profile)


def test_profile_validation_rejects_unknown_signal_reference():
    profile = json.loads(json.dumps(PROFILE_FIXTURE))
    profile["angles"][0]["signal_ids"] = ["not-a-signal"]
    with pytest.raises(ValueError, match="reference declared signals"):
        validate_profile(profile)


def test_profile_validation_rejects_subject_with_bad_slot():
    profile = json.loads(json.dumps(PROFILE_FIXTURE))
    profile["angles"][0]["subject"] = "Hello {signal_evidence} at {company}"
    with pytest.raises(ValueError, match="may only use"):
        validate_profile(profile)


def test_default_angle_may_have_no_trigger_signals():
    # The default angle has an empty signal_ids list and must validate.
    validate_profile(PROFILE_FIXTURE)


# ── store ─────────────────────────────────────────────────────────────────


def test_upsert_dedupes_by_domain(tmp_path):
    store = Store(tmp_path)
    _, created1 = store.upsert_prospect("Fixture", "fixture.example.com", "healthtech",
                                        profile_id="test-profile")
    _, created2 = store.upsert_prospect("Fixture Again", "www.fixture.example.com",
                                        "healthtech", profile_id="test-profile")
    assert created1 and not created2
    prospects = store.load_prospects()
    assert len(prospects) == 1
    assert prospects[0]["profiles"] == ["test-profile"]


def test_privacy_check_blocks_personal_fields_not_words(tmp_path):
    store = Store(tmp_path)
    # A source URL containing "personalized" is fine — the contract bans
    # personal-data FIELDS, not English words.
    store.upsert_prospect("Fixture", "fixture.example.com", "healthtech",
                          profile_id="test-profile")
    prospect = store.load_prospects()[0]
    prospect["signals"].append({"id": "llm", "profile_id": "test-profile",
                                "evidence": "personalized AI assistant",
                                "source_url": "https://example.com/personalized",
                                "observed_utc": "2026-09-02T00:00:00Z"})
    store.update_prospect(prospect["prospect_id"], signals=prospect["signals"])
    assert "personalized" in json.dumps(store.load_prospects())
    # An email FIELD is refused loudly.
    bad = dict(store.load_prospects()[0])
    bad["email"] = "someone@example.com"
    with pytest.raises(AssertionError, match="privacy contract"):
        store.save_prospects([bad])


def test_status_lifecycle_is_forward_only(tmp_path):
    store = Store(tmp_path)
    prospect, _ = store.upsert_prospect("Fixture", "fixture.example.com", "healthtech",
                                        profile_id="test-profile")
    store.update_prospect(prospect["prospect_id"], status="qualified")
    store.update_prospect(prospect["prospect_id"], status="new")  # ignored
    assert store.load_prospects()[0]["status"] == "qualified"
    with pytest.raises(ValueError, match="invalid status"):
        store.update_prospect(prospect["prospect_id"], status="bogus")


# ── discovery ─────────────────────────────────────────────────────────────


def test_seed_validation_rejects_missing_fields():
    with pytest.raises(ValueError, match="profile_id required"):
        discovery.validate_seed({"schema": "prospect_forge_seed_v1"})


def test_seed_import_is_idempotent_and_reattaches_signals(tmp_path):
    store = Store(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED_FIXTURE))
    first = discovery.import_seed(store, seed)
    assert first["added"] == ["pr-fixturehealth-example-com", "pr-wrongindustry-example-com"]
    second = discovery.import_seed(store, seed)
    assert second["added"] == [] and len(second["existing"]) == 2
    # Re-attach: a prospect created without its signals gets them on re-import.
    prospect = next(p for p in store.load_prospects() if p["domain"] == "fixturehealth.example.com")
    assert len(prospect["signals"]) == 2
    store.update_prospect(prospect["prospect_id"], signals=[])
    third = discovery.import_seed(store, seed)
    assert third["signals_attached"] >= 1


def test_rss_parser_extracts_titles_and_links():
    xml = """<?xml version="1.0"?><rss><channel>
    <item><title><![CDATA[Fixture Health ships AI assistant]]></title><link>https://example.com/a</link></item>
    <item><title>Another story</title><link>https://example.com/b</link></item>
    </channel></rss>"""
    items = parse_feed(xml)
    assert [item["link"] for item in items] == ["https://example.com/a", "https://example.com/b"]
    assert items[0]["title"] == "Fixture Health ships AI assistant"


def test_news_watch_attaches_signals_only_to_known_prospects(tmp_path):
    store = Store(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED_FIXTURE))
    discovery.import_seed(store, seed)
    xml = """<rss><channel><item>
    <title>fixturehealth.example.com ships AI assistant for patients</title>
    <link>https://example.com/story</link></item></channel></rss>"""
    result = discovery.watch_news(store, PROFILE_FIXTURE, fetch=lambda query: xml)
    assert result["queries_run"] >= 1
    assert len(result["matches"]) >= 1
    prospect = next(p for p in store.load_prospects() if p["domain"] == "fixturehealth.example.com")
    assert any("AI assistant for patients" in s["evidence"] for s in prospect["signals"])


# ── scoring ──────────────────────────────────────────────────────────────


def _prospect_with_signals(tmp_path, signals, industry="healthtech"):
    store = Store(tmp_path)
    prospect, _ = store.upsert_prospect("Fixture", "fixture.example.com", industry,
                                        profile_id="test-profile")
    if signals:
        shaped = [{"id": sid, "profile_id": "test-profile", "evidence": f"evidence {sid}",
                   "source_url": "", "observed_utc": "2026-09-02T00:00:00Z"} for sid in signals]
        store.update_prospect(prospect["prospect_id"], signals=shaped)
    return store, store.load_prospects()[0]


def test_industry_gate_blocks_wrong_industry(tmp_path):
    _, prospect = _prospect_with_signals(tmp_path, ["llm", "funding"], industry="agritech")
    fit = scoring.score_prospect(prospect, PROFILE_FIXTURE)
    assert fit["qualified"] is False and fit["score"] == 0


def test_size_gate_blocks_out_of_band(tmp_path):
    _, prospect = _prospect_with_signals(tmp_path, ["llm"])
    prospect["size_estimate"] = 100000
    fit = scoring.score_prospect(prospect, PROFILE_FIXTURE)
    assert fit["qualified"] is False


def test_tiers_follow_score_bands(tmp_path):
    _, cold = _prospect_with_signals(tmp_path, ["funding"])
    _, warm = _prospect_with_signals(tmp_path, ["llm", "funding"])
    _, hot = _prospect_with_signals(tmp_path, ["llm", "funding", "regulatory"])
    fits = [scoring.score_prospect(p, PROFILE_FIXTURE) for p in (cold, warm, hot)]
    assert [fit["tier"] for fit in fits] == ["cold", "warm", "warm"]
    assert fits[2]["score"] == 9 and fits[2]["qualified"]
    assert fits[0]["score"] == 2 and not fits[0]["qualified"]


def test_disqualification_zeroes_score(tmp_path):
    _, prospect = _prospect_with_signals(tmp_path, ["llm", "funding"])
    prospect["disqualified_by"] = [{"id": "competitor"}]
    fit = scoring.score_prospect(prospect, PROFILE_FIXTURE)
    assert fit["score"] == 0 and not fit["qualified"]


def test_foreign_profile_signals_are_not_scored(tmp_path):
    store, prospect = _prospect_with_signals(tmp_path, [])
    shaped = [{"id": "llm", "profile_id": "other-profile", "evidence": "x",
               "source_url": "", "observed_utc": "2026-09-02T00:00:00Z"}]
    store.update_prospect(prospect["prospect_id"], signals=shaped)
    fit = scoring.score_prospect(store.load_prospects()[0], PROFILE_FIXTURE)
    assert fit["score"] == 0


# ── outreach + review gate ────────────────────────────────────────────────


def _qualified_store(tmp_path, signals=("regulatory", "llm")):
    store, _ = _prospect_with_signals(tmp_path, list(signals))
    profiles = {"test-profile": PROFILE_FIXTURE}
    scoring.score_all(store, profiles)
    return store, profiles


def test_plan_picks_angle_from_strongest_signal_and_profile_subject(tmp_path):
    store, profiles = _qualified_store(tmp_path)
    plan = outreach.build_plan(store, "pr-fixture-example-com", profiles["test-profile"])
    assert plan["angle_id"] == "reg-angle"          # regulatory (4) beats llm (3)
    assert plan["subject"] == "Grounding for Fixture"
    assert plan["approach_role"] == "Chief Compliance Officer"
    assert "evidence regulatory" in plan["draft"]
    assert plan["status"] == "pending_review"


def test_plan_refuses_unqualified_prospect(tmp_path):
    store, profiles = _qualified_store(tmp_path, signals=("funding",))
    with pytest.raises(ValueError, match="not qualified"):
        outreach.build_plan(store, "pr-fixture-example-com", profiles["test-profile"])


def test_review_gate_blocks_send_before_approval(tmp_path):
    store, profiles = _qualified_store(tmp_path)
    plan = outreach.build_plan(store, "pr-fixture-example-com", profiles["test-profile"])
    with pytest.raises(ValueError, match="before review approval"):
        store.review_plan(plan["plan_id"], "sent")
    store.review_plan(plan["plan_id"], "approved")
    store.review_plan(plan["plan_id"], "sent")
    prospect = store.load_prospects()[0]
    assert prospect["status"] == "contacted"


def test_review_rejection_leaves_prospect_planned(tmp_path):
    store, profiles = _qualified_store(tmp_path)
    plan = outreach.build_plan(store, "pr-fixture-example-com", profiles["test-profile"])
    store.review_plan(plan["plan_id"], "rejected")
    assert store.load_prospects()[0]["status"] == "planned"


# ── research ──────────────────────────────────────────────────────────────


def test_research_extracts_signal_snippets(tmp_path):
    store, prospect = _prospect_with_signals(tmp_path, [])
    html = "<html><body><p>We just launched our new AI assistant for symptom checks</p></body></html>"
    found = research.research_prospect(prospect, PROFILE_FIXTURE, fetch=lambda url: html)
    assert any(f["id"] == "llm" for f in found)
    assert "AI assistant" in found[0]["evidence"]


def test_research_tolerates_fetch_failure(tmp_path):
    store, prospect = _prospect_with_signals(tmp_path, [])
    def boom(url):
        raise OSError("offline")
    assert research.research_prospect(prospect, PROFILE_FIXTURE, fetch=boom) == []


# ── report ────────────────────────────────────────────────────────────────


def test_funnel_counts_statuses_and_attention(tmp_path):
    store, profiles = _qualified_store(tmp_path)
    outreach.plan_all(store, profiles)
    data = report.funnel(store, profiles)
    assert data["total_prospects"] == 1
    assert data["plans_by_status"]["pending_review"] == 1
    assert data["needs_attention"]["plans_pending_review"] == 1


# ── full pipeline smoke ──────────────────────────────────────────────────


def test_full_pipeline_import_score_plan_review(tmp_path):
    store = Store(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED_FIXTURE))
    discovery.import_seed(store, seed)
    profiles = {"test-profile": PROFILE_FIXTURE}
    scoring.score_all(store, profiles)
    result = outreach.plan_all(store, profiles)
    assert result["planned"] == ["pl-fixturehealth-example-com-reg-angle"]
    plan = store.load_plans()[0]
    store.review_plan(plan["plan_id"], "approved")
    data = report.funnel(store, profiles)
    assert data["prospects_by_status"]["approved"] == 1
    assert data["plans_by_status"]["approved"] == 1