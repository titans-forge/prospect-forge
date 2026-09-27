"""Prospect Forge CLI: the whole funnel from one command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import dashboard, discovery, outreach, report, scoring
from .icp import load_profiles
from .store import Store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"
DATA_DIR = PROJECT_ROOT / "data"
SEEDS_DIR = DATA_DIR / "seeds"


def _store(args: argparse.Namespace) -> Store:
    return Store(args.data_dir)


def _profiles(args: argparse.Namespace) -> dict:
    return load_profiles(args.profiles_dir)


def _pick_profile(args: argparse.Namespace) -> dict:
    profiles = _profiles(args)
    profile = profiles.get(args.profile)
    if profile is None:
        raise SystemExit(f"unknown profile: {args.profile} (have: {', '.join(sorted(profiles))})")
    return profile


def cmd_profiles(args: argparse.Namespace) -> int:
    profiles = _profiles(args)
    for profile_id, profile in sorted(profiles.items()):
        print(f"{profile_id:24} {profile['product_name']}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    store = _store(args)
    result = discovery.import_seed(store, args.seed, profile_id=args.profile)
    print(f"added {len(result['added'])}, already-known {len(result['existing'])}, "
          f"signals attached {result['signals_attached']}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    store = _store(args)
    profile = _pick_profile(args)
    result = discovery.watch_news(store, profile, query_limit=args.query_limit)
    print(f"queries run: {result['queries_run']}, matches attached: {len(result['matches'])}")
    for match in result["matches"]:
        print(f"  {match['prospect_id']}: {match['title'][:90]}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    store = _store(args)
    profiles = _profiles(args)
    results = scoring.score_all(store, profiles)
    for result in results:
        parts = []
        for profile_id, fit in result["fit"].items():
            parts.append(f"{profile_id}={fit['score']} ({fit['tier']}"
                         + (", qualified" if fit["qualified"] else "") + ")")
        print(f"{result['prospect_id']:40} {'; '.join(parts)}")
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    from . import research
    store = _store(args)
    profile = _pick_profile(args)
    scanned = 0
    for prospect in store.load_prospects():
        if profile["profile_id"] not in prospect["profiles"]:
            continue
        found = research.research_prospect(prospect, profile)
        scanned += 1
        if found:
            import time
            observed = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            signals = prospect["signals"] + [
                {**signal, "observed_utc": observed} for signal in found
            ]
            store.update_prospect(prospect["prospect_id"], signals=signals,
                                  status="researched" if prospect["status"] == "new" else None)
            print(f"{prospect['prospect_id']}: {len(found)} new signal(s)")
    print(f"scanned {scanned} prospect(s)")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    store = _store(args)
    profiles = _profiles(args)
    result = outreach.plan_all(store, profiles, prospect_ids=args.prospect_ids or None)
    print(f"planned {len(result['planned'])}, skipped {len(result['skipped'])}")
    for plan_id in result["planned"]:
        print(f"  {plan_id} -> pending_review")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.plan_id is None:
        # List the review queue.
        for plan in store.load_plans():
            if plan["status"] != "pending_review":
                continue
            print(f"== {plan['plan_id']}")
            print(f"   to:   {plan['approach_role']} @ {plan['prospect_id'].removeprefix('pr-').replace('-', '.')}")
            print(f"   via:  {plan['channel_id']}")
            print(f"   sub:  {plan['subject']}")
            for line in plan["draft"].splitlines():
                print(f"   | {line}")
            for item in plan["evidence"]:
                print(f"   evidence: {item['evidence'][:90]}")
                if item["source_url"]:
                    print(f"   source:   {item['source_url'][:90]}")
            print()
        return 0
    plan = store.review_plan(args.plan_id, args.decision)
    print(f"{plan['plan_id']}: {plan['status']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    store = _store(args)
    profiles = _profiles(args)
    report.print_funnel(store, profiles)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from . import dashboard
    store = _store(args)
    profiles = _profiles(args)
    dashboard.serve(store, profiles, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prospect-forge",
                                     description="Find prospective clients, score them, draft reviewable outreach.")
    parser.add_argument("--profiles-dir", default=str(PROFILES_DIR))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles", help="list ideal-client profiles")

    p = sub.add_parser("import", help="import a seed file of candidate companies")
    p.add_argument("seed", help="path to seed JSON")
    p.add_argument("--profile", default=None, help="override the seed's profile_id")

    p = sub.add_parser("discover", help="watch public news feeds for signal mentions")
    p.add_argument("--profile", required=True)
    p.add_argument("--query-limit", type=int, default=3)

    p = sub.add_parser("score", help="score every prospect against its profiles")
    sub.add_parser("research", help="scan prospects' public sites for signal evidence")

    p = sub.add_parser("plan", help="draft outreach plans for qualified prospects")
    p.add_argument("prospect_ids", nargs="*", help="limit to specific prospects")

    p = sub.add_parser("review", help="list the review queue, or decide on one plan")
    p.add_argument("--plan-id", default=None)
    p.add_argument("--decision", choices=("approved", "rejected", "sent"), default="approved")

    sub.add_parser("report", help="print the funnel report")

    p = sub.add_parser("serve", help="run the local web dashboard (review gate)")
    p.add_argument("--host", default=dashboard.DEFAULT_HOST)
    p.add_argument("--port", type=int, default=dashboard.DEFAULT_PORT)

    args = parser.parse_args(argv)
    commands = {
        "profiles": cmd_profiles, "import": cmd_import, "discover": cmd_discover,
        "score": cmd_score, "research": cmd_research, "plan": cmd_plan,
        "review": cmd_review, "report": cmd_report, "serve": cmd_serve,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())