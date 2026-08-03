"""
Demo composer entry point — CLI form — §12.1, Phase 4.4.
Usage: python3 scripts/run_demo.py <scenario_key>
For the in-browser version (predrafted emails, click to run), use scripts/demo_server.py instead —
both share the same underlying engine (scripts/demo_engine.py), so behavior is identical either way.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from demo_engine import run_scenario, SCENARIO_ORDER

def main(scenario_key):
    result = run_scenario(scenario_key)
    trace = result["trace"]
    print(f"Ran scenario '{scenario_key}' -> final_status = {trace['final_status']}")
    for n in trace["notifications"]:
        print("--- notification ---")
        print(n["subject"])
        print(n["body"][:200])

    p, c = result["paths"], result["counts"]
    print(f"\nRendered:\n  {p['topline']} ({c['projects']} projects)\n  {p['visualizer']} ({c['steps']} steps)\n"
          f"  {p['comments']} ({c['comments']} comments)\n  {p['notifications']} ({c['notifications']} notifications)\n"
          f"  {p['activity']} ({c['activity']} activity events)")

if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "6_change_request_stakeholder_flag"
    if key not in SCENARIO_ORDER:
        print(f"Unknown scenario key '{key}'. Valid keys:\n  " + "\n  ".join(SCENARIO_ORDER))
        sys.exit(1)
    main(key)
