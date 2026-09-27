# Prospect Forge

A local-first, privacy-preserving prospect engine: find prospective clients
for your products, score them on real buying signals, and draft personalized
outreach plans — all queued for human review before anything is sent.

## Why this exists

Building products is the fun half. Finding buyers is the bottleneck. This
program systematizes distribution the same way the rest of the stack
systematizes content: a data pipeline, a scoring model, and a hard human
review gate at the end.

## Design rules

- **Local-first.** Everything is plain JSONL in `data/`. No cloud, no accounts.
- **Public sources only.** Seed imports, news RSS, public directories. No
  LinkedIn scraping, no purchased contact lists.
- **Role titles, not people.** The store keeps company names, domains, and
  role titles to approach (e.g. "Chief Compliance Officer"). It never stores
  personal contact data.
- **Drafts, never sends.** The program generates outreach plans and stops.
  A human reviews, edits, and sends manually. The review gate is the product.
- **Product-agnostic.** Each product gets an ideal-client profile (ICP) in
  `profiles/`. Adding another product = adding another JSON file.

## Workflow

```
import-seeds   ->  discover  ->  score  ->  research  ->  plan  ->  review  ->  report
   (lists)        (public)     (fit)     (evidence)   (drafts)   (the gate)  (funnel)
```

1. Define an ICP profile in `profiles/<name>.json`.
2. Import a candidate list (`data/seeds/*.json`) or run discovery against
   public news feeds.
3. Score: industry gate + weighted buying signals (funding, LLM launches,
   regulatory exposure, content hiring) minus disqualifiers → cold/warm/hot.
4. Research: fetch public pages for evidence snippets behind each signal.
5. Plan: pick an angle from the strongest signal, choose a channel, draft a
   short message that cites the specific observed evidence.
6. Review: approve, edit, or reject each plan. Approved means "ready for a
   human to send" — nothing is ever sent by the program itself.
7. Report: funnel status, what's stale, what needs attention.

## Dashboard

```bash
python3 -m prospect_forge.cli serve          # http://127.0.0.1:5213
```

The dashboard is the review gate as a page: the review queue up top (read
the draft, check the evidence link, approve/reject; approved drafts get a
"I sent this — mark sent" button), then the funnel heat rail
(cold/warm/hot), the prospect table with per-signal evidence links, and
per-product counts. It binds to loopback only and records decisions —
it never sends anything.

Double-click `Launch Prospect Forge.command` (Desktop or Vault root) to
start it and open the page in one step. Leave the terminal window open to
keep it alive.

## Install

No dependencies beyond Python 3.10+.

```bash
python3 -m prospect_forge.cli --help
```

Run from this directory, or add it to PYTHONPATH.

## Privacy contract

The store deliberately has no fields for personal names, email addresses, or
phone numbers. Outreach drafts are addressed to role titles; you resolve the
actual human at send time. This keeps the whole CRM exportable and
guilt-free.