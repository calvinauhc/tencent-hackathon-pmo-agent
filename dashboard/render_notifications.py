"""
Notifications inbox (§11) — every notification a stakeholder actually received for one project:
acknowledgment, acceptance + project ID, rejection + reason, success forecast. Previously these
were generated as data and printed to the terminal by scripts/run_demo.py, never rendered anywhere
you could look at after the fact — this is that missing view.
"""
import sys, os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import get_notifications

CSS = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:680px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.nav{font-size:12px;margin-bottom:16px}
.nav a{color:#378ADD;text-decoration:none;margin-right:14px}
.nav a:hover{text-decoration:underline}
.mail{border:1px solid #e5e3dc;border-radius:10px;margin-bottom:14px;overflow:hidden}
.mail .head{background:#f5f4f0;padding:10px 16px;font-size:13px;display:flex;justify-content:space-between}
.mail .head .to{color:#5f5e5a}
.mail .head .time{color:#999;font-size:12px}
.mail .subject{padding:12px 16px 0;font-weight:600;font-size:15px}
.mail .body{padding:8px 16px 16px;font-size:13px;line-height:1.6;white-space:pre-wrap;color:#333}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;margin-left:8px}
.tag.accept{background:#eaf3de;color:#3b6d11}
.tag.reject{background:#fcebeb;color:#a32d2d}
.tag.forecast{background:#e6f1fb;color:#1a5a92}
.tag.ack{background:#f1efe8;color:#5f5e5a}
"""

def _tag(subject):
    s = subject.lower()
    if "accepted" in s: return '<span class="tag accept">accepted</span>'
    if "not accepted" in s or "not registered" in s or "duplicate" in s: return '<span class="tag reject">rejected</span>'
    if "forecast" in s: return '<span class="tag forecast">forecast</span>'
    return '<span class="tag ack">acknowledgment</span>'

def render(project_id):
    conn = get_connection()
    proj = conn.execute("SELECT * FROM projects WHERE project_id = ? OR submission_id = ?", (project_id, project_id)).fetchone()
    proj = dict(proj) if proj else {"project_name": project_id}
    notifs = get_notifications(conn, project_id)

    items = "".join(
        f'<div class="mail"><div class="head"><span class="to">To: {n["recipient"]} · {n["channel"]}</span>'
        f'<span class="time">{datetime.fromtimestamp(float(n["sent_at"])).strftime("%b %d, %H:%M:%S")}</span></div>'
        f'<div class="subject">{n["subject"]}{_tag(n["subject"])}</div>'
        f'<div class="body">{n["body"]}</div></div>'
        for n in notifs
    ) or "<p style='color:#888'>No notifications sent yet for this project.</p>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Notifications — {project_id}</title>
<style>{CSS}</style></head><body>
<div class="nav"><a href="/" target="_top">← Composer</a><a href="topline.html">Topline</a><a href="activity.html">Activity feed</a>
<a href="visualizer_{project_id}.html">Execution flow</a><a href="comments_{project_id}.html">Comments</a></div>
<h3>{proj.get('project_name')} — Notifications ({len(notifs)})</h3>
{items}
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"notifications_{project_id}.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, len(notifs)

if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "PRJ-2026-0791"
    path, n = render(pid)
    print(f"rendered {path} with {n} notifications")
