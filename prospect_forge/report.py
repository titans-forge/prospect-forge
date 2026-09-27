"""Funnel report: where every prospect and plan stands, at a glance."""

from __future__ import annotations

from typing import Any

from .scoring import TIER_ORDER
from .store import Store


def funnel(store: Store, profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prospects = store.load_prospects()
    plans = store.load_plans()
    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {tier: 0 for tier in TIER_ORDER}
    by_profile: dict[str, dict[str, Any]] = {}
    for prospect in prospects:
        by_status[prospect["status"]] = by_status.get(prospect["status"], 0) + 1
        for profile_id, fit in prospect.get("fit", {}).items():
            entry = by_profile.setdefault(profile_id, {
                "profile": profiles.get(profile_id, {}).get("product_name", profile_id),
                "prospects": 0, "qualified": 0, "hot": 0,
            })
            entry["prospects"] += 1
            if fit.get("qualified"):
                entry["qualified"] += 1
            if fit.get("tier") == "hot":
                entry["hot"] += 1
        best = max((fit.get("tier", "cold") for fit in prospect.get("fit", {}).values()),
                   key=lambda tier: TIER_ORDER.index(tier) if tier in TIER_ORDER else 0,
                   default="cold")
        by_tier[best] += 1
    plan_status: dict[str, int] = {}
    for plan in plans:
        plan_status[plan["status"]] = plan_status.get(plan["status"], 0) + 1
    return {
        "schema": "prospect_forge_report_v1",
        "total_prospects": len(prospects),
        "prospects_by_status": by_status,
        "prospects_by_tier": by_tier,
        "by_profile": by_profile,
        "plans_by_status": plan_status,
        "needs_attention": {
            "plans_pending_review": plan_status.get("pending_review", 0),
            "prospects_never_scored": sum(1 for p in prospects if not p.get("fit")),
            "approved_not_sent": plan_status.get("approved", 0),
        },
    }


def print_funnel(store: Store, profiles: dict[str, dict[str, Any]]) -> None:
    data = funnel(store, profiles)
    print(f"Prospects: {data['total_prospects']}")
    for status, count in sorted(data["prospects_by_status"].items()):
        print(f"  {status:12} {count}")
    print("Tiers:")
    for tier in TIER_ORDER:
        print(f"  {tier:12} {data['prospects_by_tier'][tier]}")
    print("Profiles:")
    for profile_id, entry in sorted(data["by_profile"].items()):
        print(f"  {entry['profile']}: {entry['prospects']} prospects, "
              f"{entry['qualified']} qualified, {entry['hot']} hot")
    print("Plans:")
    for status, count in sorted(data["plans_by_status"].items()):
        print(f"  {status:16} {count}")
    attention = data["needs_attention"]
    print("Needs attention:")
    print(f"  plans pending review: {attention['plans_pending_review']}")
    print(f"  approved but not sent: {attention['approved_not_sent']}")
    print(f"  never scored:          {attention['prospects_never_scored']}")