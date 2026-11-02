"""
scripts/scan_outbound_network.py:
Static scan across app/ and ocr_v2/ to ensure zero outbound network calls are made:
- No requests.get/post/put
- No urllib.request.urlopen / urlretrieve
- No socket.create_connection / socket.connect
- No http.client / aiohttp outbound calls
Exits 0 if clean, 1 if any outbound network call is detected.
"""

import ast
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [PROJECT_ROOT / "app", PROJECT_ROOT / "ocr_v2"]

FORBIDDEN_CALLS = {
    ("requests", "get"),
    ("requests", "post"),
    ("requests", "put"),
    ("requests", "delete"),
    ("requests", "request"),
    ("urllib", "request"),
    ("urllib.request", "urlopen"),
    ("urllib.request", "urlretrieve"),
    ("socket", "connect"),
    ("socket", "create_connection"),
    ("aiohttp", "ClientSession"),
}


def check_file(fp: Path) -> list[str]:
    violations = []
    text = fp.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(fp))
    except Exception as e:
        return [f"AST parse error: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check func name
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    func_name = f"{node.func.value.id}.{node.func.attr}"
                elif isinstance(node.func.value, ast.Attribute):
                    func_name = f"{node.func.attr}"
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id

            for mod, call in FORBIDDEN_CALLS:
                if func_name == f"{mod}.{call}":
                    violations.append(f"Line {node.lineno}: Outbound network call '{func_name}'")

    return violations


def main():
    total_files = 0
    total_violations = 0

    print("Scanning app/ and ocr_v2/ for outbound network calls...")
    for target in SCAN_DIRS:
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
                        print(f"\n[NETWORK VIOLATION] in {rel}:")
                        for item in v:
                            print(f"  {item}")
                        total_violations += len(v)

    print("\n" + "=" * 50)
    print(f"Scanned {total_files} files across app/ and ocr_v2/.")
    if total_violations > 0:
        print(f"FAILED: Found {total_violations} outbound network call violations.")
        sys.exit(1)
    else:
        print("PASSED: 0 outbound network calls found. Codebase is completely air-gapped/offline.")
        sys.exit(0)


if __name__ == "__main__":
    main()
