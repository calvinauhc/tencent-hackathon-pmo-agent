#!/bin/bash
# Runs all 5 phase test files in order. Exit code is nonzero if any phase fails.
set -e
cd "$(dirname "$0")"
echo "=== Phase 1 ===" && python3 tests/scenarios/test_phase1.py
echo "=== Phase 2 ===" && python3 tests/eval/test_phase2.py
echo "=== Phase 3 ===" && python3 tests/scenarios/test_phase3.py
echo "=== Phase 4 ===" && python3 tests/eval/test_phase4.py
echo "=== Phase 5 ===" && python3 tests/eval/test_phase5.py
echo "=== Phase 6 ===" && python3 tests/scenarios/test_phase6.py
echo "=== Phase 7 ===" && python3 tests/scenarios/test_phase7.py
echo "=== Phase 8 ===" && python3 tests/scenarios/test_phase8.py
echo "=== Phase 9 ===" && python3 tests/scenarios/test_phase9.py
echo "=== Phase 10 ===" && python3 tests/scenarios/test_phase10.py
echo
echo "All phases passed."
