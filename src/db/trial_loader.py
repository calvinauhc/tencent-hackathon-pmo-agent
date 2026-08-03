"""Loads data/trial-projects.json — §14 trial data, §3 schema shape."""
import json, os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.shared.schemas import Project

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trial-projects.json")

def load_trial_data():
    with open(DATA_PATH, "r") as f:
        raw = json.load(f)
    projects = [Project(**p) for p in raw["projects"]]
    return projects, raw["scenario_index"]

if __name__ == "__main__":
    projects, idx = load_trial_data()
    print(f"loaded {len(projects)} trial projects")
    print(f"scenario_index has {len(idx)} scenarios")
