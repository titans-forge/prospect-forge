"""Fit scoring: does this company look like a buyer for this product?

Scoring is deliberately transparent and boring: an industry gate, a size
band check, weighted buying signals, minus disqualifiers. Every point is
traceable to an observed signal with evidence. No ML, no magic — the human
reviewing the plan can reproduce the number by hand.
"""

from __future__ import annotations

from typing import Any

# Tier bands for the summed signal weight (after the industry + size gates).
TIERS = {"cold": (0, 4), "warm": (5, 9), "hot": (10, 10**9)}
TIER_ORDER = ("cold", "warm", "hot")


def tier_for(score: int) -> str:
    for name, (low, high) in TIERS.items():
        if low <= score <= high:
            return name
    return "cold"


def score_prospect(prospect: dict[str, Any], profile: dict[str, Any],
                   *, signal_ids: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score one prospect against one profile. Returns the fit block.

    The industry gate is hard: a company outside the profile's industries
    never qualifies, however many signals it has. Size gates only apply when
    both the prospect size and the profile bands are known.
    """
    signals = signal_ids or {s["id"]: s for s in profile["signals"]}
    breakdown: list[dict[str, Any]] = []

    industry_ok = prospect["industry"].strip().lower() in {
        industry.strip().lower() for industry in profile["industries"]
    }
    if not industry_ok:
        return {
            "profile_id": profile["profile_id"],
            "score": 0,
            "tier": "cold",
            "qualified": False,
            "breakdown": [{"gate": "industry", "reason": f"industry {prospect['industry']!r} outside profile"}],
        }

    size = prospect.get("size_estimate")
    bands = profile.get("size_bands", [])
    size_ok = size is None or not bands or any(
        band["min"] <= size <= band["max"] for band in bands
    )
    if not size_ok:
        return {
            "profile_id": profile["profile_id"],
            "score": 0,
            "tier": "cold",
            "qualified": False,
            "breakdown": [{"gate": "size", "reason": f"size {size} outside bands"}],
        }

    score = 0
    for signal in prospect["signals"]:
        definition = signals.get(signal["id"])
        if definition is None:
            continue  # signal from another profile; not scored here
        if signal.get("profile_id", profile["profile_id"]) != profile["profile_id"]:
            continue
        score += definition["weight"]
        breakdown.append({
            "signal": signal["id"],
            "points": definition["weight"],
            "evidence": signal.get("evidence", ""),
            "source_url": signal.get("source_url", ""),
        })

    disqualified = [d["id"] for d in prospect.get("disqualified_by", [])]
    if disqualified:
        score = 0
        breakdown.append({"disqualified_by": disqualified})

    return {
        "profile_id": profile["profile_id"],
        "score": score,
        "tier": tier_for(score),
        "qualified": score >= TIERS["warm"][0] and not disqualified,
        "breakdown": breakdown,
    }


def score_all(store: Any, profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Score every prospect against every profile it is a candidate for."""
    results = []
    for prospect in store.load_prospects():
        fits = {}
        for profile_id in prospect["profiles"]:
            profile = profiles.get(profile_id)
            if profile is None:
                continue
            fit = score_prospect(prospect, profile)
            fits[profile_id] = fit
        prospect["fit"] = fits
        if any(fit["qualified"] for fit in fits.values()) and prospect["status"] == "new":
            prospect["status"] = "qualified"
        store.update_prospect(prospect["prospect_id"], fit=fits, status=prospect["status"])
        results.append({"prospect_id": prospect["prospect_id"], "fit": fits})
    return results