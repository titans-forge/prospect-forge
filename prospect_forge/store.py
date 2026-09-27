"""Local JSONL store: prospects and outreach plans, no cloud, no accounts."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

STORE_SCHEMA = "prospect_forge_store_v1"
PROSPECT_FILE = "prospects.jsonl"
PLANS_FILE = "plans.jsonl"
DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")

# Prospect lifecycle. A prospect can only move forward (or be rejected);
# "contacted" is set by the human after they actually send an approved plan.
PROSPECT_STATUSES = ("new", "researched", "qualified", "planned", "approved", "contacted", "rejected")
PLAN_STATUSES = ("pending_review", "approved", "rejected", "sent")

# Privacy contract: the store has no fields for personal names, email
# addresses, or phone numbers. Outreach targets role titles only. The check
# walks field NAMES (not serialized values — a source URL may legitimately
# contain the word "personalized" without being personal data).
_FORBIDDEN_KEYS = ("email", "phone", "first_name", "last_name", "personal")


def _assert_no_personal_fields(obj: Any, where: str = "prospect") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            for forbidden in _FORBIDDEN_KEYS:
                assert forbidden not in key, \
                    f"privacy contract violated: field {key!r} in {where}"
            _assert_no_personal_fields(value, f"{where}.{key}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _assert_no_personal_fields(item, f"{where}[{index}]")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_domain(value: str) -> str:
    domain = value.strip().lower().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0].split(":")[0].removeprefix("www.")
    if not DOMAIN_RE.fullmatch(domain):
        raise ValueError(f"invalid domain: {value}")
    return domain


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── prospects ────────────────────────────────────────────────────────

    def _prospect_path(self) -> Path:
        return self.data_dir / PROSPECT_FILE

    def load_prospects(self) -> list[dict[str, Any]]:
        path = self._prospect_path()
        if not path.is_file():
            return []
        prospects = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                prospects.append(json.loads(line))
        return prospects

    def save_prospects(self, prospects: list[dict[str, Any]]) -> None:
        for prospect in prospects:
            _assert_no_personal_fields(prospect)
        path = self._prospect_path()
        path.write_text("".join(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n"
                                for p in prospects), encoding="utf-8")

    def upsert_prospect(self, name: str, domain: str, industry: str,
                        *, profile_id: str, size_estimate: int | None = None,
                        source: str = "manual") -> tuple[dict[str, Any], bool]:
        """Add a prospect or attach a profile interest to an existing one.

        Returns (prospect, created).
        """
        domain = normalize_domain(domain)
        if not name.strip() or not industry.strip():
            raise ValueError("name and industry are required")
        prospects = self.load_prospects()
        existing = next((p for p in prospects if p["domain"] == domain), None)
        if existing is not None:
            if profile_id not in existing["profiles"]:
                existing["profiles"].append(profile_id)
                existing["updated_utc"] = _now()
                self.save_prospects(prospects)
            return existing, False
        prospect = {
            "schema": STORE_SCHEMA,
            "prospect_id": f"pr-{domain.replace('.', '-')}",
            "name": name.strip(),
            "domain": domain,
            "industry": industry.strip(),
            "size_estimate": size_estimate,
            "profiles": [profile_id],
            "signals": [],
            "disqualified_by": [],
            "fit": {},
            "status": "new",
            "sources": [{"kind": source, "observed_utc": _now()}],
            "notes": [],
            "created_utc": _now(),
            "updated_utc": _now(),
        }
        prospects.append(prospect)
        self.save_prospects(prospects)
        return prospect, True

    def update_prospect(self, prospect_id: str, **fields: Any) -> dict[str, Any]:
        prospects = self.load_prospects()
        prospect = next((p for p in prospects if p["prospect_id"] == prospect_id), None)
        if prospect is None:
            raise KeyError(f"unknown prospect: {prospect_id}")
        status = fields.pop("status", None)
        if status is not None:
            if status not in PROSPECT_STATUSES:
                raise ValueError(f"invalid status: {status}")
            current = PROSPECT_STATUSES.index(prospect["status"])
            target = PROSPECT_STATUSES.index(status)
            if target > current:  # forward-only lifecycle
                prospect["status"] = status
        for key, value in fields.items():
            if key not in {"signals", "disqualified_by", "fit", "sources", "notes",
                           "size_estimate", "industry", "name"}:
                raise ValueError(f"unsupported prospect field: {key}")
            prospect[key] = value
        prospect["updated_utc"] = _now()
        self.save_prospects(prospects)
        return prospect

    # ── plans ─────────────────────────────────────────────────────────────

    def _plan_path(self) -> Path:
        return self.data_dir / PLANS_FILE

    def load_plans(self) -> list[dict[str, Any]]:
        path = self._plan_path()
        if not path.is_file():
            return []
        plans = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                plans.append(json.loads(line))
        return plans

    def save_plans(self, plans: list[dict[str, Any]]) -> None:
        path = self._plan_path()
        path.write_text("".join(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n"
                                for p in plans), encoding="utf-8")

    def add_plan(self, prospect_id: str, profile_id: str, angle_id: str,
                 channel_id: str, approach_role: str, subject: str, draft: str,
                 evidence: list[dict[str, Any]]) -> dict[str, Any]:
        plans = self.load_plans()
        plan_id = f"pl-{prospect_id.removeprefix('pr-')}-{angle_id}"
        if any(plan["plan_id"] == plan_id for plan in plans):
            raise ValueError(f"plan already exists for this prospect and angle: {plan_id}")
        plan = {
            "schema": STORE_SCHEMA,
            "plan_id": plan_id,
            "prospect_id": prospect_id,
            "profile_id": profile_id,
            "angle_id": angle_id,
            "channel_id": channel_id,
            "approach_role": approach_role,
            "subject": subject,
            "draft": draft,
            "evidence": evidence,
            "status": "pending_review",
            "created_utc": _now(),
            "updated_utc": _now(),
        }
        plans.append(plan)
        self.save_plans(plans)
        return plan

    def review_plan(self, plan_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected", "sent"}:
            raise ValueError("decision must be approved|rejected|sent")
        plans = self.load_plans()
        plan = next((p for p in plans if p["plan_id"] == plan_id), None)
        if plan is None:
            raise KeyError(f"unknown plan: {plan_id}")
        if plan["status"] == "pending_review" and decision == "sent":
            raise ValueError("cannot mark sent before review approval")
        plan["status"] = decision
        plan["updated_utc"] = _now()
        self.save_plans(plans)
        if decision in {"approved", "sent"}:
            self.update_prospect(plan["prospect_id"],
                                 status="approved" if decision == "approved" else "contacted")
        return plan