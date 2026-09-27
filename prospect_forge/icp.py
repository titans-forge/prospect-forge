"""Ideal-client profiles: one JSON file per product defines who buys it."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ICP_SCHEMA = "prospect_forge_icp_v1"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
TEMPLATE_SLOTS = {"company", "signal_evidence", "value_prop", "proof_point"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"invalid profile: {message}")


def validate_profile(profile: Any) -> dict[str, Any]:
    """Validate one ICP profile without mutating it."""
    _require(isinstance(profile, dict), "profile must be an object")
    _require(profile.get("schema") == ICP_SCHEMA, "schema must be prospect_forge_icp_v1")
    profile_id = profile.get("profile_id")
    _require(isinstance(profile_id, str) and bool(PROFILE_ID_RE.fullmatch(profile_id)),
             "profile_id must be kebab-case")
    for field in ("product_name", "value_prop"):
        _require(isinstance(profile.get(field), str) and profile[field].strip(),
                 f"{field} required")
    _require(isinstance(profile.get("proof_points"), list) and profile["proof_points"]
             and all(isinstance(item, str) and item.strip() for item in profile["proof_points"]),
             "proof_points required")
    industries = profile.get("industries")
    _require(isinstance(industries, list) and industries
             and all(isinstance(item, str) and item.strip() for item in industries),
             "industries required")
    bands = profile.get("size_bands")
    _require(isinstance(bands, list) and bands, "size_bands required")
    for index, band in enumerate(bands):
        _require(isinstance(band, dict), f"size_bands[{index}] must be an object")
        _require(isinstance(band.get("min"), int) and band["min"] >= 0,
                 f"size_bands[{index}].min must be a non-negative integer")
        _require(isinstance(band.get("max"), int) and band["max"] >= band["min"],
                 f"size_bands[{index}].max must be >= min")
    signals = profile.get("signals")
    _require(isinstance(signals, list) and signals, "signals required")
    seen_signal_ids: set[str] = set()
    for index, signal in enumerate(signals):
        where = f"signals[{index}]"
        _require(isinstance(signal, dict), f"{where} must be an object")
        _require(isinstance(signal.get("id"), str) and signal["id"].strip(), f"{where}.id required")
        _require(signal["id"] not in seen_signal_ids, f"{where}.id duplicate")
        seen_signal_ids.add(signal["id"])
        _require(isinstance(signal.get("weight"), int) and 1 <= signal["weight"] <= 10,
                 f"{where}.weight must be an integer 1-10")
        _require(isinstance(signal.get("description"), str) and signal["description"].strip(),
                 f"{where}.description required")
        _require(isinstance(signal.get("keywords"), list) and signal["keywords"],
                 f"{where}.keywords required")
    roles = profile.get("approach_roles")
    _require(isinstance(roles, list) and roles
             and all(isinstance(item, str) and item.strip() for item in roles),
             "approach_roles required")
    channels = profile.get("channels")
    _require(isinstance(channels, list) and channels, "channels required")
    seen_channel_ids: set[str] = set()
    for index, channel in enumerate(channels):
        where = f"channels[{index}]"
        _require(isinstance(channel, dict), f"{where} must be an object")
        _require(isinstance(channel.get("id"), str) and channel["id"].strip(), f"{where}.id required")
        _require(channel["id"] not in seen_channel_ids, f"{where}.id duplicate")
        seen_channel_ids.add(channel["id"])
        _require(isinstance(channel.get("label"), str) and channel["label"].strip(),
                 f"{where}.label required")
    angles = profile.get("angles")
    _require(isinstance(angles, list) and angles, "angles required")
    seen_angle_ids: set[str] = set()
    for index, angle in enumerate(angles):
        where = f"angles[{index}]"
        _require(isinstance(angle, dict), f"{where} must be an object")
        _require(isinstance(angle.get("id"), str) and angle["id"].strip(), f"{where}.id required")
        _require(angle["id"] not in seen_angle_ids, f"{where}.id duplicate")
        seen_angle_ids.add(angle["id"])
        _require(isinstance(angle.get("template"), str) and angle["template"].strip(),
                 f"{where}.template required")
        subject = angle.get("subject")
        if subject is not None:
            _require(isinstance(subject, str) and subject.strip(), f"{where}.subject invalid")
            used_subject = set(re.findall(r"\{(\w+)\}", subject))
            _require(used_subject <= {"company"},
                     f"{where}.subject may only use the {{company}} slot")
        if angle.get("approach_role") is not None:
            _require(isinstance(angle["approach_role"], str) and angle["approach_role"].strip(),
                     f"{where}.approach_role invalid")
        used = set(re.findall(r"\{(\w+)\}", angle["template"]))
        _require(used <= TEMPLATE_SLOTS,
                 f"{where}.template uses unknown slots: {sorted(used - TEMPLATE_SLOTS)}")
        _require("signal_evidence" in used, f"{where}.template must use {{signal_evidence}}")
        _require(isinstance(angle.get("signal_ids"), list),
                 f"{where}.signal_ids required")
        # An angle with no trigger signals is the fallback/default angle.
        _require(all(signal_id in seen_signal_ids for signal_id in angle["signal_ids"]),
                 f"{where}.signal_ids must reference declared signals")
    _require(isinstance(profile.get("default_channel"), str)
             and profile["default_channel"] in seen_channel_ids,
             "default_channel must reference a declared channel")
    return profile


def load_profiles(profiles_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load and validate every profile in the directory, keyed by profile_id."""
    directory = Path(profiles_dir)
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        profile = validate_profile(json.loads(path.read_text(encoding="utf-8")))
        _require(profile["profile_id"] not in profiles,
                 f"duplicate profile_id: {profile['profile_id']}")
        profiles[profile["profile_id"]] = profile
    return profiles


def signal_map(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {signal["id"]: signal for signal in profile["signals"]}