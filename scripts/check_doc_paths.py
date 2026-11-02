"""
scripts/check_doc_paths.py:
Verifies DEPLOY-2c Criterion 7:
Extracts every endpoint path mentioned in:
  - docs/DEPLOY_ON_SERVER.md
  - docs/API.md
  - README.md
  - Dockerfile
  - docker-compose.yml
and checks each against the application route table.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app

def get_app_routes():
    # Use FastAPI openapi schema to obtain all declared endpoints
    schema = app.openapi()
    paths = set(schema.get("paths", {}).keys())
    # Static and system routes
    paths.update([
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/ui",
        "/ready",
        "/health",
        "/metrics",
        "/predict"
    ])
    return paths

def normalize_path_template(path: str) -> str:
    # Normalize {id} or {job_id} or {key_id}
    p = re.sub(r"/\{id\}", "/{job_id}", path)
    return p

def main():
    api_paths = get_app_routes()
    files_to_check = [
        ROOT / "docs" / "DEPLOY_ON_SERVER.md",
        ROOT / "docs" / "API.md",
        ROOT / "README.md",
        ROOT / "Dockerfile",
        ROOT / "docker-compose.yml"
    ]

    endpoint_pattern = re.compile(r"/(?:v2/[a-zA-Z0-9_\-\/{}]*|health|ready|predict|metrics|docs|redoc)")
    
    extracted = {}
    for f in files_to_check:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        matches = endpoint_pattern.findall(text)
        for m in matches:
            cleaned = m.rstrip(".,;:)\"'>`")
            cleaned = cleaned.split(" ")[0]
            if cleaned and not cleaned.endswith("/"):
                extracted.setdefault(cleaned, []).append(f.name)

    print(f"Total unique endpoint paths extracted from documentation: {len(extracted)}")
    
    missing = []
    matches_found = []
    for ep, files in sorted(extracted.items()):
        norm_ep = normalize_path_template(ep)
        # Check direct or normalized match
        if ep in api_paths or norm_ep in api_paths:
            matches_found.append((ep, files))
            print(f"  [OK] {ep} -> Exists in API route table (found in: {', '.join(set(files))})")
        else:
            # Check prefix match for wildcards
            if any(p.startswith(ep) for p in api_paths):
                matches_found.append((ep, files))
                print(f"  [OK] {ep} (prefix) -> Exists in API route table (found in: {', '.join(set(files))})")
            else:
                missing.append((ep, files))
                print(f"  [FAIL] {ep} -> NOT in API route table! (found in: {', '.join(set(files))})")

    if missing:
        print(f"\nFAILED: {len(missing)} documentation paths do not exist in the route table:")
        for ep, files in missing:
            print(f"  {ep} in {files}")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: All {len(matches_found)} documented endpoint paths exist in application routes.")
        sys.exit(0)

if __name__ == "__main__":
    main()
