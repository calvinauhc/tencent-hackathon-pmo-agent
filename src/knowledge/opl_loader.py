"""
§7.2.4 — reads back the OPLs Agent 13 publishes (src/agents/agent13_opl_composer.py writes to
data/opl/{project_id}.md). Mirrors docs_loader.py's flat-file-read pattern for playbook/pvp; this is
the RAG-ready corpus (§5's "RAG only if it grows" escape hatch actually firing) whereas playbook/pvp
stay CAG since they're ~1 page each and don't grow.
"""
import os

OPL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "opl")


def load_opl(project_id) -> str:
    """Returns the OPL's full markdown text, or "" if this project has none (most projects won't —
    only ones that reached `completed` and ran Agent 13)."""
    if not project_id:
        return ""
    path = os.path.join(OPL_DIR, f"{project_id}.md")
    if not os.path.isfile(path):
        return ""
    with open(path, "r") as f:
        return f.read()


def extract_section(opl_text: str, heading: str) -> str:
    """Pulls the text under a `## {heading}` markdown section, up to the next `## ` or end of doc —
    used to pull just "What worked / what to reuse" out of a full OPL without handing Agent 5 the
    whole retrospective (§7.2.4)."""
    if not opl_text:
        return ""
    marker = f"## {heading}"
    idx = opl_text.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    next_idx = opl_text.find("\n## ", start)
    section = opl_text[start:next_idx] if next_idx != -1 else opl_text[start:]
    return section.strip()


def list_opl_project_ids() -> list:
    """Every project with a published OPL on file — used by Agent 2 to know which completed
    projects have richer text to fold into its similarity corpus (§7.2.4)."""
    if not os.path.isdir(OPL_DIR):
        return []
    return [f[:-3] for f in os.listdir(OPL_DIR) if f.endswith(".md")]
