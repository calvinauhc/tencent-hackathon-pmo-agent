"""Comment and Concern Panel (§9.2) — static render of real project_comments rows plus the
two composer forms (PMO decision vs stakeholder flag). Forms are illustrative in this static
build (no server to post to yet) — the permission split itself is what's demonstrated."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.db.client import get_connection
from src.db.repositories import get_project, get_comments

def render(project_id):
    conn = get_connection()
    proj = conn.execute("SELECT * FROM projects WHERE project_id = ? OR submission_id = ?", (project_id, project_id)).fetchone()
    proj = dict(proj) if proj else {"project_name": project_id, "project_id": project_id}
    comments = get_comments(conn, project_id)

    items = "".join(
        f'<div style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #eee">'
        f'<b>{c["author"]}</b> <span style="color:#888;font-size:12px">· {c["role"]}</span> '
        + ('<span style="background:#faeeda;color:#854f0b;font-size:11px;padding:2px 8px;border-radius:6px">flagged concern</span>' if c["is_flagged_concern"] else '')
        + f'<div style="margin-top:4px">{c["body"]}</div></div>'
        for c in comments
    ) or "<p style='color:#888'>No comments yet.</p>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Comments — {project_id}</title>
<style>body{{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:600px;margin:2rem auto;padding:0 1rem}}
textarea{{width:100%;min-height:60px;margin-bottom:8px}}
.composer{{border-top:1px solid #ddd;padding-top:14px;margin-top:14px}}
button{{margin-right:8px;padding:6px 14px;border:1px solid #999;border-radius:6px;background:#fff}}
.nav{{font-size:12px;margin-bottom:16px}}
.nav a{{color:#378ADD;text-decoration:none;margin-right:14px}}
.nav a:hover{{text-decoration:underline}}
</style></head><body>
<div class="nav"><a href="/" target="_top">← Composer</a><a href="topline.html">Topline</a><a href="activity.html">Activity feed</a>
<a href="visualizer_{project_id}.html">Execution flow</a><a href="notifications_{project_id}.html">Notifications</a></div>
<h3>{proj.get('project_name')} — {project_id}</h3>
{items}
<div class="composer"><div style="color:#888;font-size:12px;margin-bottom:6px">Posting as PMO</div>
<textarea placeholder="Add a comment or decision note"></textarea>
<div style="font-size:11px;color:#888;margin-bottom:8px">Comments here can be attached to a gate decision.</div>
<button>Accept</button><button>Reject</button><button>Post comment</button></div>
<div class="composer"><div style="color:#888;font-size:12px;margin-bottom:6px">Posting as stakeholder</div>
<textarea placeholder="Add a note or flag a concern"></textarea>
<label style="font-size:13px"><input type="checkbox"> Flag as a concern for PMO review</label><br><br>
<button>Post comment</button></div>
</body></html>"""
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"comments_{project_id}.html"))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path, len(comments)

if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "PRJ-2026-0791"
    path, n = render(pid)
    print(f"rendered {path} with {n} comments")
