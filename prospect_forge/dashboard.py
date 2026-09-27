"""Local web dashboard for Prospect Forge: the review gate, as a page.

Serves a single self-contained page on 127.0.0.1 that shows the whole
funnel — the review queue, the tier heat rail, prospects, and plans —
and lets a human approve, reject, or mark plans sent. The dashboard is
the review gate: it records decisions, it never sends anything.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import scoring
from .report import funnel
from .store import Store

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5213


def state_payload(store: Store, profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Everything the page needs, in one GET."""
    return {
        "schema": "prospect_forge_dashboard_v1",
        "funnel": funnel(store, profiles),
        "profiles": {pid: p["product_name"] for pid, p in profiles.items()},
        "prospects": store.load_prospects(),
        "plans": store.load_plans(),
    }


def make_handler(store: Store, profiles: dict[str, dict[str, Any]]) -> type:
    class DashboardHandler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, content_type: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            self._send(code, json.dumps(payload, ensure_ascii=False), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json(200, state_payload(store, profiles))
            elif self.path == "/api/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "request body must be JSON"})
                return
            if self.path == "/api/review":
                try:
                    plan = store.review_plan(body.get("plan_id", ""),
                                             body.get("decision", ""))
                except (ValueError, KeyError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"ok": True, "plan": plan})
            elif self.path == "/api/score":
                scoring.score_all(store, profiles)
                self._json(200, {"ok": True, "state": state_payload(store, profiles)})
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
            pass

    return DashboardHandler


def serve(store: Store, profiles: dict[str, dict[str, Any]],
          *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the dashboard until interrupted. Binds loopback only."""
    server = ThreadingHTTPServer((host, port), make_handler(store, profiles))
    print(f"Prospect Forge dashboard on http://{host}:{port}/ "
          f"(store: {store.data_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prospect Forge</title>
<style>
  :root {
    color-scheme: light;
    --paper: #edf0f3;
    --card: #ffffff;
    --ink: #1b2733;
    --muted: #5b6b7b;
    --line: #d7dde3;
    --cold: #4c6e91;
    --warm: #b96e14;
    --hot: #bf3d0c;
    --cold-bg: #e3eaf1;
    --warm-bg: #f6e8d3;
    --hot-bg: #f8ddd2;
    --accent: #8a3a12;
    --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .wrap { max-width: 1060px; margin: 0 auto; padding: 28px 24px 80px; }

  header { border-bottom: 2px solid var(--ink); padding-bottom: 14px; }
  .eyebrow {
    font: 600 11px/1 var(--mono); letter-spacing: .18em; text-transform: uppercase;
    color: var(--accent); margin: 0 0 6px;
  }
  h1 {
    font: 700 34px/1.1 var(--serif); margin: 0 0 4px; letter-spacing: -.01em;
  }
  .tagline { color: var(--muted); font-size: 14px; margin: 0; }
  .header-row { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
  button {
    font: 600 13px/1 var(--mono); padding: 9px 14px; border-radius: 6px;
    border: 1px solid var(--ink); background: var(--card); color: var(--ink);
    cursor: pointer;
  }
  button:hover { background: #e8ebee; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  button.primary { background: var(--ink); color: var(--card); }
  button.primary:hover { background: #2c3c4d; }
  button.hot { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.hot:hover { background: var(--hot); border-color: var(--hot); }

  h2 {
    font: 700 21px/1.2 var(--serif); margin: 40px 0 4px;
    display: flex; align-items: baseline; gap: 10px;
  }
  h2 .count { font: 600 12px/1 var(--mono); color: var(--paper); background: var(--ink);
    border-radius: 999px; padding: 4px 9px; }
  .sub { color: var(--muted); font-size: 13px; margin: 0 0 14px; }

  .banner {
    background: var(--hot-bg); border: 1px solid var(--hot); border-radius: 8px;
    padding: 12px 16px; margin-top: 22px; font-size: 14px;
  }
  .banner strong { color: var(--hot); }

  /* review cards */
  .plan-card {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 20px 22px; margin-bottom: 14px; border-left: 4px solid var(--warm);
  }
  .plan-card.rejected { border-left-color: var(--line); opacity: .62; }
  .plan-card.approved { border-left-color: var(--cold); }
  .plan-card.sent { border-left-color: var(--cold); opacity: .8; }
  .plan-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 12.5px; color: var(--muted);
    font-family: var(--mono); margin-bottom: 10px; }
  .plan-meta .co { color: var(--ink); font-weight: 700; font-size: 15px; font-family: -apple-system, sans-serif; }
  .subject { font: 600 17px/1.3 var(--serif); margin: 2px 0 10px; }
  .draft {
    font: 15px/1.6 var(--serif); white-space: pre-wrap; margin: 0 0 12px;
    padding: 14px 16px; background: #f7f9fa; border-radius: 8px; border: 1px solid var(--line);
  }
  .evidence { font-size: 12.5px; color: var(--muted); margin: 0 0 14px; padding: 0; list-style: none; }
  .evidence li { margin-bottom: 4px; }
  .evidence a { color: var(--cold); }
  .plan-actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .status-chip {
    font: 600 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase;
    padding: 5px 9px; border-radius: 999px; background: var(--cold-bg); color: var(--cold);
  }
  .status-chip.warm { background: var(--warm-bg); color: var(--warm); }
  .status-chip.hot { background: var(--hot-bg); color: var(--hot); }

  /* heat rail */
  .rail {
    display: flex; height: 46px; border-radius: 8px; overflow: hidden;
    border: 1px solid var(--line); margin: 10px 0 6px;
  }
  .rail .seg { display: flex; align-items: center; justify-content: center;
    font: 700 13px/1 var(--mono); }
  .rail .seg.cold { background: var(--cold-bg); color: var(--cold); }
  .rail .seg.warm { background: var(--warm-bg); color: var(--warm); }
  .rail .seg.hot  { background: var(--hot-bg);  color: var(--hot); }
  .rail .seg.zero { background: #f2f4f6; color: var(--muted); }
  .rail-key { font: 12px var(--mono); color: var(--muted); display: flex; justify-content: space-between; }

  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
  .chip {
    background: var(--card); border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 13px 6px 10px; font-size: 13.5px; display: flex; align-items: center; gap: 8px;
  }
  .chip .dot { width: 9px; height: 9px; border-radius: 50%; }
  .chip .score { font: 700 12px var(--mono); color: var(--muted); }

  /* prospects table */
  table { width: 100%; border-collapse: collapse; background: var(--card);
    border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: 14px; }
  th { text-align: left; font: 600 11px var(--mono); letter-spacing: .1em; text-transform: uppercase;
    color: var(--muted); padding: 10px 14px; border-bottom: 1px solid var(--line); background: #f5f7f9; }
  td { padding: 11px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  td.mono { font-family: var(--mono); font-size: 12.5px; color: var(--muted); }
  details summary { cursor: pointer; color: var(--cold); font-size: 12.5px; }
  details ul { margin: 8px 0 0; padding-left: 18px; color: var(--muted); font-size: 12.5px; }
  details a { color: var(--cold); word-break: break-all; }

  .empty {
    background: var(--card); border: 1px dashed var(--line); border-radius: 10px;
    padding: 22px 20px; color: var(--muted); font-size: 14px;
  }
  .empty code { font-family: var(--mono); background: #f0f2f4; padding: 1px 6px; border-radius: 4px; }

  .toast {
    position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
    background: var(--ink); color: var(--paper); padding: 10px 18px; border-radius: 8px;
    font-size: 14px; opacity: 0; transition: opacity .25s; pointer-events: none;
  }
  .toast.show { opacity: 1; }
  @media (prefers-reduced-motion: reduce) { .toast { transition: none; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="header-row">
      <div>
        <p class="eyebrow">Local sales bench</p>
        <h1>Prospect Forge</h1>
        <p class="tagline">Public sources only &middot; role titles, never personal data &middot; nothing sends until you approve it.</p>
      </div>
      <button id="rescore" title="Re-score every prospect against its profiles">Re-score</button>
    </div>
  </header>
  <main id="main"><p class="sub">Loading…</p></main>
</div>
<div class="toast" id="toast"></div>

<script>
"use strict";
const $main = document.getElementById("main");
const $toast = document.getElementById("toast");
let state = null;
let toastTimer = null;

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function toast(msg) {
  $toast.textContent = msg;
  $toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove("show"), 1800);
}

async function refresh() {
  const res = await fetch("/api/state");
  state = await res.json();
  render();
}

async function act(planId, decision, label) {
  const res = await fetch("/api/review", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({plan_id: planId, decision}),
  });
  const data = await res.json();
  if (!res.ok) { toast(data.error || "request failed"); return; }
  toast(label);
  refresh();
}

document.getElementById("rescore").addEventListener("click", async () => {
  const res = await fetch("/api/score", {method: "POST"});
  const data = await res.json();
  if (res.ok) { state = data.state; render(); toast("Re-scored"); }
});

const TIERS = {cold: "var(--cold)", warm: "var(--warm)", hot: "var(--hot)"};
const STATUS_ORDER = ["pending_review", "approved", "sent", "rejected"];

function prospectById(id) {
  return (state.prospects || []).find(p => p.prospect_id === id) || {};
}
function bestFit(prospect) {
  const fits = Object.values(prospect.fit || {});
  if (!fits.length) return null;
  return fits.reduce((a, b) => (b.score > a.score ? b : a));
}
function planStatusPlan(s) { return STATUS_ORDER.indexOf(s); }

function renderReview(plans) {
  const pending = plans.filter(p => p.status === "pending_review");
  const acted = plans.filter(p => p.status !== "pending_review")
    .sort((a, b) => planStatusPlan(a.status) - planStatusPlan(b.status));
  const ordered = pending.concat(acted);
  let html = `<h2>Review queue${pending.length ? ` <span class="count">${pending.length} waiting</span>` : ""}</h2>
  <p class="sub">Read the draft, check the evidence link, then approve or reject. Approved drafts are yours to send — mark them sent here once you have.</p>`;
  if (!ordered.length) {
    html += `<div class="empty">No outreach drafts yet. Run <code>python3 -m prospect_forge.cli plan</code> to draft plans for every qualified prospect.</div>`;
    return html;
  }
  for (const plan of ordered) {
    const prospect = prospectById(plan.prospect_id);
    const statusChip = `<span class="status-chip">${esc(plan.status.replace("_", " "))}</span>`;
    const actions = plan.status === "pending_review"
      ? `<button class="primary" data-act="approved" data-id="${esc(plan.plan_id)}">Approve</button>
         <button data-act="rejected" data-id="${esc(plan.plan_id)}">Reject</button>`
      : plan.status === "approved"
        ? `<button class="hot" data-act="sent" data-id="${esc(plan.plan_id)}">I sent this — mark sent</button>`
        : "";
    html += `
    <section class="plan-card ${esc(plan.status)}">
      <div class="plan-meta">
        <span class="co">${esc(prospect.name || plan.prospect_id)}</span>
        <span>${esc(prospect.domain || "")}</span>
        <span>to: ${esc(plan.approach_role)}</span>
        <span>via: ${esc(plan.channel_id)}</span>
        <span>angle: ${esc(plan.angle_id)}</span>
        ${statusChip}
      </div>
      <div class="subject">${esc(plan.subject)}</div>
      <div class="draft">${esc(plan.draft)}</div>
      <ul class="evidence">${(plan.evidence || []).map(e => `
        <li><a href="${esc(e.source_url)}" target="_blank" rel="noreferrer">${esc(e.evidence)}</a></li>`).join("")}
      </ul>
      <div class="plan-actions">${actions}</div>
    </section>`;
  }
  return html;
}

function renderRail() {
  const f = state.funnel;
  const tiers = f.prospects_by_tier || {};
  const total = f.total_prospects || 0;
  const none = Math.max(0, total - (tiers.cold + tiers.warm + tiers.hot));
  const pct = n => total ? (100 * n / total).toFixed(1) + "%" : "0%";
  const seg = (cls, n, label) => n
    ? `<div class="seg ${cls}" style="width:${pct(n)}">${n} ${label}</div>` : "";
  let html = `<h2>Funnel</h2>
  <p class="sub">${total} prospect${total === 1 ? "" : "s"} across ${Object.keys(state.profiles).length} product profile${Object.keys(state.profiles).length === 1 ? "" : "s"}. A prospect is qualified when it clears the industry and size gates and reaches the warm band.</p>
  <div class="rail" role="img" aria-label="Prospects by tier: ${tiers.cold} cold, ${tiers.warm} warm, ${tiers.hot} hot">
    ${seg("cold", tiers.cold, "cold")}
    ${seg("warm", tiers.warm, "warm")}
    ${seg("hot", tiers.hot, "hot")}
    ${seg("zero", none, "not scored")}
  </div>
  <div class="rail-key"><span>cold 0–4</span><span>warm 5–9</span><span>hot 10+</span></div>
  <div class="chips">`;
  const scored = [...state.prospects].sort((a, b) =>
    (bestFit(b)?.score ?? -1) - (bestFit(a)?.score ?? -1));
  for (const p of scored) {
    const fit = bestFit(p);
    const tier = fit ? fit.tier : "cold";
    const score = fit ? fit.score : "–";
    html += `<span class="chip"><span class="dot" style="background:${TIERS[tier] || "var(--muted)"}"></span>
      ${esc(p.name)} <span class="score">${score}</span></span>`;
  }
  html += `</div>`;
  const attention = f.needs_attention || {};
  const notes = [];
  if (attention.plans_pending_review) notes.push(`${attention.plans_pending_review} plan${attention.plans_pending_review === 1 ? "" : "s"} waiting for review`);
  if (attention.approved_not_sent) notes.push(`${attention.approved_not_sent} approved plan${attention.approved_not_sent === 1 ? "" : "s"} not yet sent`);
  if (attention.prospects_never_scored) notes.push(`${attention.prospects_never_scored} prospect${attention.prospects_never_scored === 1 ? "" : "s"} never scored`);
  if (notes.length) html += `<div class="banner"><strong>Needs attention:</strong> ${esc(notes.join(" · "))}.</div>`;
  return html;
}

function renderProfiles() {
  const byProfile = state.funnel.by_profile || {};
  let html = `<h2>Products</h2><p class="sub">One profile per product — who buys it, what signals to look for, what to say.</p>`;
  const entries = Object.entries(byProfile);
  if (!entries.length) {
    html += `<div class="empty">No scored prospects yet. Import a seed, then run <code>score</code>.</div>`;
    return html;
  }
  html += `<table><tr><th>Product</th><th>Prospects</th><th>Qualified</th><th>Hot</th></tr>`;
  for (const [pid, e] of entries) {
    html += `<tr><td>${esc(e.profile)}</td><td class="mono">${e.prospects}</td>
      <td class="mono">${e.qualified}</td><td class="mono">${e.hot}</td></tr>`;
  }
  return html + `</table>`;
}

function renderProspects() {
  let html = `<h2>Prospects</h2><p class="sub">Every company in the store, with the public evidence behind each signal.</p>`;
  const rows = [...state.prospects].sort((a, b) =>
    (bestFit(b)?.score ?? -1) - (bestFit(a)?.score ?? -1));
  if (!rows.length) {
    html += `<div class="empty">The store is empty. Run <code>python3 -m prospect_forge.cli import &lt;seed.json&gt;</code>.</div>`;
    return html;
  }
  html += `<table>
    <tr><th>Company</th><th>Industry</th><th>Status</th><th>Best fit</th><th>Signals</th></tr>`;
  for (const p of rows) {
    const fit = bestFit(p);
    const chip = fit ? `<span class="status-chip ${fit.tier}">${fit.tier} ${fit.score}${fit.qualified ? " · qualified" : ""}</span>`
                     : `<span class="status-chip">not scored</span>`;
    html += `<tr>
      <td><strong>${esc(p.name)}</strong><br><span class="mono">${esc(p.domain)}</span></td>
      <td>${esc(p.industry)}</td>
      <td class="mono">${esc(p.status)}</td>
      <td>${chip}</td>
      <td>${p.signals.length}
        <details><summary>evidence</summary><ul>${p.signals.map(s => `
          <li><strong>${esc(s.id)}</strong> — ${esc(s.evidence)}<br>
          <a href="${esc(s.source_url)}" target="_blank" rel="noreferrer">${esc(s.source_url || "no source recorded")}</a></li>`).join("")}
        </ul></details></td>
    </tr>`;
  }
  return html + `</table>`;
}

function render() {
  const plans = state.plans || [];
  const pending = plans.filter(p => p.status === "pending_review").length;
  document.title = pending ? `(${pending}) Prospect Forge` : "Prospect Forge";
  $main.innerHTML =
    (pending ? `<div class="banner"><strong>${pending} outreach draft${pending === 1 ? "" : "s"} need${pending === 1 ? "s" : ""} your review.</strong> Nothing goes out until you approve it.</div>` : "") +
    renderReview(plans) + renderRail() + renderProspects() + renderProfiles();
  for (const btn of $main.querySelectorAll("button[data-act]")) {
    btn.addEventListener("click", () => {
      const labels = {approved: "Approved", rejected: "Rejected", sent: "Marked sent"};
      act(btn.dataset.id, btn.dataset.act, labels[btn.dataset.act]);
    });
  }
}

refresh();
</script>
</body>
</html>
"""