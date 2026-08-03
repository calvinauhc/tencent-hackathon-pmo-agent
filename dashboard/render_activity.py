"""
Portfolio activity feed — every agent step and every comment across ALL projects, merged into one
time-ordered feed. This is the missing view of "what's actually happening across the 100 records":
before this, audit_log/comments could only be seen one project at a time (visualizer/comments
panel), so there was no way to watch the workflow touch the wider portfolio.
"""
import sys, os, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import get_recent_audit_log, get_recent_comments

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
.nav a:hover{text-decoration:underline}
.feed{border-left:2px solid #e5e3dc;margin-left:6px}
.item{position:relative;padding:6px 0 14px 20px}
.item::before{content:'';position:absolute;left:-7px;top:9px;width:12px;height:12px;border-radius:50%;background:#ccc;border:2px solid #fff}
.item.agent::before{background:#378ADD}
.item.accept::before{background:#639922}
.item.reject::before{background:#e24b4a}
.item.comment::before{background:#ef9f27}
.item.flag::before{background:#e24b4a}
.meta{font-size:11px;color:#999;margin-bottom:2px}
.meta .pid{color:#378ADD;font-weight:600}
.desc{font-size:13px}
.desc b{font-weight:600}
.flagbadge{font-size:10px;background:#fcebeb;color:#a32d2d;padding:1px 6px;border-radius:5px;margin-left:6px}
"""

DESCRIBE = {
    ("agent1_intake_parser", "validate"): lambda p: "Intake validated" + (f" — missing {', '.join(p.get('missing_fields', []))}" if p.get("missing_fields") else ""),
    ("agent2_duplicate_checker", "check"): lambda p: f"Duplicate check: {p.get('verdict', '—')}",
    ("agent3_duplicate_rejection_notifier", "notify"): lambda p: "Duplicate-rejection notice sent",
    ("agent4_pmo_router", "notify"): lambda p: "Acknowledgment sent — entered PMO review",
    ("agent5_business_impact", "analyze"): lambda p: f"Business impact analyzed: {p.get('margin_impact', '—')}",
    ("agent6_knowledge_crosscheck", "crosscheck"): lambda p: f"Knowledge cross-check: {p.get('verdict', '—')}",
    ("agent7_acceptance_handler", "accept"): lambda p: f"Accepted — project ID {p.get('project_id', '—')} issued",
    ("agent8_rejection_feedback_composer", "compose"): lambda p: "Rejected — feedback composed",
    ("agent9_dashboard_service", "publish"): lambda p: "Published to portfolio dashboard",
    ("agent10_success_predictor", "score"): lambda p: f"Success score computed: {p.get('success_score', '—')}/100",
}
KIND = {
    "agent7_acceptance_handler": "accept",
    "agent8_rejection_feedback_composer": "reject",
    "agent3_duplicate_rejection_notifier": "reject",
}

def render(limit=60):
    conn = get_connection()
    audit_rows = get_recent_audit_log(conn, limit=limit)
    comment_rows = get_recent_comments(conn, limit=limit)

    events = []
    for r in audit_rows:
        payload = json.loads(r["payload"]) if r["payload"] else {}
        desc_fn = DESCRIBE.get((r["agent"], r["action"]))
        desc = desc_fn(payload) if desc_fn else f"{r['agent']} · {r['action']}"
        events.append({
            "ts": float(r["created_at"]), "kind": KIND.get(r["agent"], "agent"),
            "project_id": r["project_id"], "html": desc,
        })
    for c in comment_rows:
        kind = "flag" if c["is_flagged_concern"] else "comment"
        badge = '<span class="flagbadge">flagged concern</span>' if c["is_flagged_concern"] else ""
        events.append({
            "ts": float(c["created_at"]), "kind": kind, "project_id": c["project_id"],
            "html": f'<b>{c["author"]}</b> ({c["role"]}) commented{badge}: {c["body"]}',
        })

    events.sort(key=lambda e: e["ts"], reverse=True)
    events = events[:limit]

    items = "".join(
        f'<div class="item {e["kind"]}"><div class="meta">'
        f'<span class="pid">{e["project_id"]}</span> · {datetime.fromtimestamp(e["ts"]).strftime("%b %d, %H:%M:%S")}</div>'
        f'<div class="desc">{e["html"]}</div></div>'
        for e in events
    ) or "<p style='color:#888'>No activity yet — run scripts/run_demo.py to generate some.</p>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Portfolio Activity Feed</title>
<style>{CSS}</style></head><body>
<div class="nav"><a href="/" target="_top">← Composer</a><a href="topline.html">Topline</a></div>
<h3>Portfolio activity — last {len(events)} events across all projects</h3>
<div class="feed">{items}</div>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "activity.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, len(events)

if __name__ == "__main__":
    path, n = render()
    print(f"rendered {path} with {n} events")
