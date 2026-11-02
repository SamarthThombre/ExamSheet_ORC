"""
scripts/check_imports.py:
Scans all python files under app/ and ocr_v2/ for forbidden imports or path references:
- experiments/
- tests/
- tests_v2/
- legacy ocr/ package
Exits with code 1 if any forbidden import or path reference is detected, 0 otherwise.
"""

import ast
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_DIRS = [PROJECT_ROOT / "app", PROJECT_ROOT / "ocr_v2"]

FORBIDDEN_MODULES = {"experiments", "tests", "tests_v2", "ocr"}


def check_file(filepath: Path) -> list[str]:
    violations = []
    text = filepath.read_text(encoding="utf-8")

    try:
        tree = ast.parse(text, filename=str(filepath))
    except Exception as e:
        return [f"AST parse error: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg in FORBIDDEN_MODULES:
                    violations.append(f"Line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in FORBIDDEN_MODULES:
                    violations.append(f"Line {node.lineno}: from {node.module} import ...")

    lines = text.splitlines()
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for forbidden in ["experiments/", "experiments\\\\", "tests/", "tests\\\\", "tests_v2/"]:
            if f'"{forbidden}' in line or f"'{forbidden}'" in line:
                violations.append(f"Line {idx}: reference to forbidden path string '{forbidden}'")

    return violations


def main():
    total_files = 0
    total_violations = 0

    print("Checking import hygiene in app/ and ocr_v2/...")
    for target in TARGET_DIRS:
        if not target.exists():
            continue
        for root, _, files in os.walk(target):
            for f in files:
                if f.endswith(".py"):
                    total_files += 1
                    fp = Path(root) / f
                    v = check_file(fp)
                    if v:
                        rel = fp.relative_to(PROJECT_ROOT)
                        print(f"\n[VIOLATION] in {rel}:")
                        for item in v:
                            print(f"  {item}")
                        total_violations += len(v)

    print("\n" + "=" * 50)
    print(f"Scanned {total_files} files across app/ and ocr_v2/.")
    if total_violations > 0:
        print(f"FAILED: Found {total_violations} forbidden import/path violations.")
        sys.exit(1)
    else:
        print("PASSED: 0 forbidden imports or path references found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
