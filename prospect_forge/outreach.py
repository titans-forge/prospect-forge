"""Outreach planner: turn qualified prospects into reviewable draft plans.

The planner picks an angle from the prospect's strongest signal, suggests a
channel and a role title to approach, and fills a short template with the
specific observed evidence. The result lands in the review queue — a human
edits and sends it. The program never sends anything.
"""

from __future__ import annotations

from typing import Any

from .store import Store


def strongest_signal(prospect: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the prospect's highest-weight signal that the profile declares."""
    weights = {signal["id"]: signal["weight"] for signal in profile["signals"]}
    best = None
    for signal in prospect.get("signals", []):
        if signal.get("profile_id", profile["profile_id"]) != profile["profile_id"]:
            continue
        weight = weights.get(signal["id"])
        if weight is None:
            continue
        if best is None or weight > weights[best["id"]]:
            best = signal
    return best


def pick_angle(profile: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pick the angle whose trigger signals include the strongest signal."""
    if signal is None:
        return next((angle for angle in profile["angles"] if not angle["signal_ids"]), None)
    for angle in profile["angles"]:
        if signal["id"] in angle["signal_ids"]:
            return angle
    return None


def render(template: str, *, company: str, signal_evidence: str,
           value_prop: str, proof_point: str) -> str:
    return (template.replace("{company}", company)
                    .replace("{signal_evidence}", signal_evidence)
                    .replace("{value_prop}", value_prop)
                    .replace("{proof_point}", proof_point))


def build_plan(store: Store, prospect_id: str, profile: dict[str, Any],
               *, approach_role: str | None = None) -> dict[str, Any]:
    """Draft one outreach plan for a qualified prospect. Returns the plan.

    The draft cites the single strongest piece of observed evidence — the
    message is about the company's own situation, not about us.
    """
    prospect = next(p for p in store.load_prospects() if p["prospect_id"] == prospect_id)
    fit = prospect["fit"].get(profile["profile_id"])
    if fit is None:
        raise ValueError(f"prospect not scored against profile {profile['profile_id']}")
    if not fit["qualified"]:
        raise ValueError("prospect is not qualified for this profile")

    signal = strongest_signal(prospect, profile)
    angle = pick_angle(profile, signal)
    if angle is None:
        raise ValueError("no angle matches the prospect's signals; add a default angle")

    draft = render(
        angle["template"],
        company=prospect["name"],
        signal_evidence=(signal["evidence"] if signal else "your recent AI content work"),
        value_prop=profile["value_prop"],
        proof_point=profile["proof_points"][0],
    )
    subject = angle.get("subject", "A specific idea for {company}").format(company=prospect["name"])
    evidence = [{
        "signal": signal["id"],
        "evidence": signal["evidence"],
        "source_url": signal.get("source_url", ""),
    }] if signal else []

    plan = store.add_plan(
        prospect_id=prospect_id,
        profile_id=profile["profile_id"],
        angle_id=angle["id"],
        channel_id=profile["default_channel"],
        approach_role=approach_role or angle.get("approach_role") or profile["approach_roles"][0],
        subject=subject,
        draft=draft,
        evidence=evidence,
    )
    store.update_prospect(prospect_id, status="planned")
    return plan


def plan_all(store: Store, profiles: dict[str, dict[str, Any]],
             *, prospect_ids: list[str] | None = None) -> dict[str, Any]:
    """Plan every qualified prospect that has no plan yet."""
    planned, skipped = [], []
    existing = {(plan["prospect_id"], plan["profile_id"]) for plan in store.load_plans()}
    for prospect in store.load_prospects():
        if prospect_ids is not None and prospect["prospect_id"] not in prospect_ids:
            continue
        for profile_id, fit in prospect.get("fit", {}).items():
            if not fit.get("qualified"):
                continue
            if (prospect["prospect_id"], profile_id) in existing:
                skipped.append(prospect["prospect_id"])
                continue
            try:
                plan = build_plan(store, prospect["prospect_id"], profiles[profile_id])
                planned.append(plan["plan_id"])
            except ValueError:
                skipped.append(prospect["prospect_id"])
    return {"planned": planned, "skipped": skipped}