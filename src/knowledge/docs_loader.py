"""Loads the 4 synthetic knowledge docs (§5, §7.1) as plain text for CAG (whole-doc-in-context)."""
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

DOC_FILES = {
    "playbook": "playbook.md",
    "pvp": "pvp.md",
    "political": "political.md",
    "regulatory": "regulatory.md",
}

def load_doc(doc_type: str) -> str:
    path = os.path.join(DATA_DIR, DOC_FILES[doc_type])
    with open(path, "r") as f:
        return f.read()

def load_all_docs() -> dict:
    return {k: load_doc(k) for k in DOC_FILES}
