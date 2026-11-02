# Server Deployment and Verification Guide

This runbook provides complete, copy-pasteable commands to deploy, verify, and monitor the Exam Paper OCR Extractor API service in an on-premise production server environment.

---

## 1. Quickstart: Docker & Compose Deployment

### Step 1: Clone Repository and Check Weights
```bash
cd /opt/exam_paper_extractor

# Verify local vendored model weights are present (air-gapped)
ls -lh models/ppocrv6/rec_ppocr_v6.onnx
ls -lh models/ppocrv6/dict_ppocr_v6.txt
```

### Step 2: Build and Launch Production Container
```bash
# Build multi-stage container
docker compose build

# Start service in background
docker compose up -d

# Verify container status
docker compose ps
docker compose logs -f --tail=50
```

---

## 2. Health and Readiness Checks via `curl`

### Liveness Probe (`/health`)
Verifies HTTP connectivity, API version, manifest hash, and active engine:
```bash
curl -s http://localhost:8000/health | jq .
```
*Expected response:*
```json
{
  "status": "ok",
  "version": "2.0.0",
  "engine_name": "v2",
  "manifest_hash": "<sha256>",
  "ocr_loaded": true,
  "detector_loaded": true,
  "model_path": "models/ppocrv6/rec_ppocr_v6.onnx"
}
```

### Readiness Probe (`/ready`)
Verifies ONNX model file integrity and SHA-256 checksums before traffic is routed:
```bash
curl -s -w "\nHTTP Status: %{http_code}\n" http://localhost:8000/ready
```
*Expected response:*
```json
{"status": "ready", "ready": true, "checksums_verified": true}
HTTP Status: 200
```

---

## 3. 15-Sheet Identity Check Script

Execute this script to verify that live `/v2/predict` output matches the frozen baseline outputs identically:

```bash
#!/usr/bin/env bash
set -euo pipefail

ADMIN_KEY="ep_admin_master_secret_key_deploy2"
BASE_URL="http://localhost:8000"

echo "=== Running 15-Sheet Verification Check against ${BASE_URL} ==="

python3 - << 'EOF'
import json
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:8000"
ADMIN_KEY = "ep_admin_master_secret_key_deploy2"
SHEETS_FILE = Path("experiments/deploy/identity_sheets.json")

if not SHEETS_FILE.exists():
    print(f"Error: {SHEETS_FILE} not found.")
    exit(1)

with open(SHEETS_FILE, "r", encoding="utf-8") as f:
    sheets = json.load(f)

print(f"Loaded {len(sheets)} reference test sheets.")
success_count = 0

for item in sheets:
    fn = item["filename"]
    p = Path(item["path"])
    if not p.exists():
        print(f"Skipping {fn} (image not present on server)")
        continue

    # Build multipart upload
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    data = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fn}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/v2/predict?extract_question_marks=true",
        data=data,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-API-Key": ADMIN_KEY,
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            tot = res_json.get("total_marks", {}).get("value")
            roll = res_json.get("enrolment", {}).get("value")
            print(f"  OK: {fn} -> Roll={roll}, Total={tot}")
            success_count += 1
    except Exception as e:
        print(f"  FAIL: {fn} -> {e}")

print(f"\nVerification Complete: {success_count}/{len(sheets)} sheets matched successfully.")
EOF
```

---

## 4. Fresh Virtual Environment Setup (`requirements-prod.txt`)

For bare-metal or standalone virtual environment deployment:

```bash
# 1. Create fresh isolated environment
python3 -m venv .venv_prod
source .venv_prod/bin/activate  # On Windows: .venv_prod\Scripts\activate

# 2. Upgrade pip and install production-only dependencies
pip install --upgrade pip
pip install -r requirements-prod.txt

# 3. Export pip freeze and verify against checked-in package manifest
pip freeze > pip_freeze_current.txt
diff -u experiments/deploy2/pip_freeze.txt pip_freeze_current.txt || true

# 4. Start production Uvicorn server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## 5. Reverse Proxy Setup (Caddy with Automatic HTTPS & HSTS)

To expose the service securely over HTTPS with HSTS and strict origin controls:

```bash
# Install Caddy on Debian/Ubuntu
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# Deploy Caddyfile from repository
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy
```
