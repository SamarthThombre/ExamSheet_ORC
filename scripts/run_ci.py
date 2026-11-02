#!/usr/bin/env python3
"""
scripts/run_ci.py: Unified CI verification runner for local and automation environments.
Executes:
1. scripts/check_imports.py (Import boundary checks)
2. scripts/scan_outbound_network.py (Air-gap / zero outbound network scan)
3. pytest tests_v2/ (Full v2 test suite including auth, validation, privacy, operations)
"""

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def run_step(name: str, cmd: list) -> bool:
    print(f"\n==================================================")
    print(f"CI STEP: {name}")
    print(f"Command: {' '.join(cmd)}")
    print(f"==================================================")
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        print(f"\n[FAIL] Step '{name}' exited with return code {res.returncode}")
        return False
    print(f"\n[PASS] Step '{name}' completed successfully.")
    return True

def main():
    py_exe = sys.executable

    steps = [
        ("Import Hygiene & Tier Isolation", [py_exe, str(ROOT / "scripts" / "check_imports.py")]),
        ("Outbound Network Static Audit", [py_exe, str(ROOT / "scripts" / "scan_outbound_network.py")]),
        ("v2 Test Suite", [py_exe, "-m", "pytest", "tests_v2/"]),
    ]

    for name, cmd in steps:
        if not run_step(name, cmd):
            print("\n==================================================")
            print("CI FAILED: One or more stages failed.")
            print("==================================================")
            sys.exit(1)

    print("\n==================================================")
    print("CI PASSED: All stages completed successfully.")
    print("==================================================")
    sys.exit(0)

if __name__ == "__main__":
    main()
