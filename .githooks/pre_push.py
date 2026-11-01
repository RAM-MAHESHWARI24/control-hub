#!/usr/bin/env python3
"""
Control Hub - Tier 2 Comprehensive Pre-Push Regression Gate
Executes prior to `git push` to guarantee that all standalone regression tests
and core imports pass cleanly before publishing commits.
"""

import os
import sys
import subprocess
from pathlib import Path

# Safeguard Windows stdout encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent

def run_suite(name, cmd):
    print(f"\n▶ Running: {name}...")
    p = subprocess.run(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print(f"❌ [FAIL] {name} exited with status {p.returncode}:")
        print(p.stdout)
        return False
    print(f"✅ [PASS] {name}")
    return True

def main():
    print("==============================================================")
    print(" 🚀 CONTROL HUB - TIER 2 PRE-PUSH VERIFICATION")
    print("==============================================================")

    suites = [
        ("Control Hub Standalone Unit Tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("Module Import Smoke Check", [sys.executable, "-c", "import server; import config; import core; import widgets; print('Modules imported cleanly.')"]),
    ]

    all_passed = True
    for name, cmd in suites:
        if not run_suite(name, cmd):
            all_passed = False
            break

    print("\n==============================================================")
    if not all_passed:
        print("🛑 PRE-PUSH CHECKS FAILED: Git push rejected to prevent defect escalation.")
        sys.exit(1)

    print("🎉 ALL PRE-PUSH SUITES PASSED (100%): Proceeding with git push.")
    sys.exit(0)

if __name__ == "__main__":
    main()
