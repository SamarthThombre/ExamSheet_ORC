"""Local web server for the Sheet Data Extractor teacher portal."""

import argparse
import csv
import http.server
import json
import mimetypes
import os
import re
import socketserver
import sys
import tempfile
import webbrowser
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlsplit

PORT = 3000
HOST = "127.0.0.1"
DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = DIRECTORY.parent
LABELS_CSV = PROJECT_ROOT / "data" / "canonical_labels.csv"
IMAGES_DIR = PROJECT_ROOT / "data" / "raw" / "images"
DATASETS = {
    "legacy": {
        "labels_csv": LABELS_CSV,
        "images_dir": IMAGES_DIR,
    },
    "v3": {
        "labels_csv": PROJECT_ROOT / "data" / "canonical_labels_v3.csv",
        "images_dir": PROJECT_ROOT / "data" / "data_v3" / "images",
        "enrollment_prefix": "0801CA25",
        "subject_code": "CT10716",
    },
    "v4": {
        "labels_csv": PROJECT_ROOT / "data" / "canonical_labels_v4.csv",
        "images_dir": PROJECT_ROOT / "data" / "data_v4" / "images",
        "enrollment_prefix": "0801CA25",
        "subject_code": "CT10222",
    },
}
ACTIVE_DATASET = "legacy"
MARK_FIELDS = ("q1", "q2", "q3", "q4", "q5", "grand_total")
EXTRA_FIELDS = (*MARK_FIELDS, "marks_status")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MARK_EXPRESSION_PATTERN = re.compile(r"^\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)*$")
ENROLLMENT_PATTERN = re.compile(r"^[A-Za-z0-9/-]{4,32}$")


def read_label_records(csv_path=LABELS_CSV, images_dir=IMAGES_DIR):
    """Return image rows with old labels retained as marks-labeling defaults."""
    records = {}
    fieldnames = []
    if csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames or []
            for row in reader:
                filename = (row.get("image_filename") or "").strip()
                if filename:
                    records[filename] = row

    image_names = sorted(
        path.name
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ) if images_dir.is_dir() else []

    items = []
    for filename in image_names:
        row = records.get(filename, {})
        items.append({
            "image_filename": filename,
            "enrollment_no": row.get("enrollment_no", ""),
            "subject_code": row.get("subject_code", ""),
            "q1": row.get("q1", ""),
            "q2": row.get("q2", ""),
            "q3": row.get("q3", ""),
            "q4": row.get("q4", ""),
            "q5": row.get("q5", ""),
            "grand_total": row.get("grand_total") or row.get("total_marks", ""),
            "marks_status": row.get("marks_status", ""),
        })
    return items, fieldnames


def validate_mark_values(payload):
    """Evaluate addition expressions and validate v2-compatible marks fields."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object of marks.")

    values = {}
    for field in MARK_FIELDS:
        value = payload.get(field, "")
        if value is None:
            value = ""
        value = str(value).strip()
        if value and not MARK_EXPRESSION_PATTERN.fullmatch(value):
            raise ValueError(f"{field} must be a number, an addition such as 2.5+0.5, or blank.")
        if value:
            try:
                result = sum(
                    (Decimal(term.strip()) for term in value.split("+")),
                    Decimal(0),
                )
            except InvalidOperation as error:
                raise ValueError(f"{field} contains an invalid number.") from error
            if result > 70:
                raise ValueError(f"{field} must be between 0 and 70.")
            value = format(result.normalize(), "f")
        if value and Decimal(value) < 0:
            raise ValueError(f"{field} must be between 0 and 70.")
        values[field] = value

    if not values["grand_total"]:
        raise ValueError("grand_total is required.")
    return values


def save_mark_record(
    filename,
    payload,
    csv_path=LABELS_CSV,
    images_dir=IMAGES_DIR,
    enrollment_prefix=None,
):
    """Update one label row atomically without dropping its original columns."""
    if Path(filename).name != filename or Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Invalid image filename.")
    image_path = images_dir / filename
    if not image_path.is_file() or image_path.resolve().parent != images_dir.resolve():
        raise FileNotFoundError(f"Image not found: {filename}")

    values = validate_mark_values(payload)
    rows = {}
    fieldnames = [
        "image_filename", "enrollment_no", "subject_code", "grand_total",
        "q1", "q2", "q3", "q4", "q5", "status", "marks_status",
    ]
    if csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
            for row in reader:
                row_name = (row.get("image_filename") or "").strip()
                if row_name:
                    rows[row_name] = row

    for field in EXTRA_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    row = rows.get(filename, {"image_filename": filename})
    row.update(values)
    enrollment_no = str(payload.get("enrollment_no") or row.get("enrollment_no") or "").strip()
    subject_code = str(payload.get("subject_code") or row.get("subject_code") or "").strip()
    if enrollment_prefix:
        if not re.fullmatch(r"\d{4}", enrollment_no):
            raise ValueError("Enter the four digits after the fixed enrollment prefix.")
        enrollment_no = f"{enrollment_prefix}{enrollment_no}"
    elif not ENROLLMENT_PATTERN.fullmatch(enrollment_no):
        raise ValueError("Enter a valid enrollment number (4–32 letters, digits, /, or -).")
    if not subject_code or len(subject_code) > 40:
        raise ValueError("Subject code is required and must be at most 40 characters.")
    row["enrollment_no"] = enrollment_no
    row["subject_code"] = subject_code
    if "total_marks" in fieldnames:
        row["total_marks"] = values["grand_total"]
    row["marks_status"] = "verified"
    row.setdefault("status", "verified")
    row.setdefault("enrollment_no", "")
    row.setdefault("subject_code", "")
    row.setdefault("sheet_no", "")
    rows[filename] = row

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=csv_path.parent,
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            writer = csv.DictWriter(temp_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row_name in sorted(rows):
                writer.writerow(rows[row_name])
        os.replace(temp_path, csv_path)
    except OSError:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise
    return row

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def end_headers(self):
        # Prevent caching for quick development / demo iteration
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def send_json(self, status_code, body):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def get_dataset(self):
        return DATASETS[ACTIVE_DATASET]

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/labels":
            dataset = self.get_dataset()
            images_dir = dataset["images_dir"]
            labels_csv = dataset["labels_csv"]
            if not images_dir.is_dir():
                self.send_json(500, {"error": f"Image directory not found: {images_dir}"})
                return
            try:
                items, _ = read_label_records(labels_csv, images_dir)
            except OSError as error:
                self.send_json(500, {"error": f"Could not read label data: {error}"})
                return
            self.send_json(200, {
                "items": items,
                "dataset": ACTIVE_DATASET,
                "enrollment_prefix": dataset.get("enrollment_prefix", ""),
                "subject_code": dataset.get("subject_code", ""),
            })
            return

        if parsed.path.startswith("/api/images/"):
            filename = unquote(parsed.path.removeprefix("/api/images/"))
            if Path(filename).name != filename or Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
                self.send_json(400, {"error": "Invalid image filename."})
                return
            images_dir = self.get_dataset()["images_dir"]
            image_path = images_dir / filename
            if not image_path.is_file() or image_path.resolve().parent != images_dir.resolve():
                self.send_json(404, {"error": "Image not found."})
                return
            try:
                content = image_path.read_bytes()
            except OSError as error:
                self.send_json(500, {"error": f"Could not read image: {error}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(image_path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlsplit(self.path)
        prefix = "/api/labels/"
        if not parsed.path.startswith(prefix):
            self.send_json(404, {"error": "Endpoint not found."})
            return

        filename = unquote(parsed.path[len(prefix):])
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid Content-Length."})
            return
        if content_length <= 0 or content_length > 8192:
            self.send_json(413, {"error": "Request body must be between 1 and 8192 bytes."})
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            dataset = self.get_dataset()
            row = save_mark_record(
                filename,
                payload,
                dataset["labels_csv"],
                dataset["images_dir"],
                dataset.get("enrollment_prefix"),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "Request body must contain valid JSON."})
            return
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
            return
        except FileNotFoundError as error:
            self.send_json(404, {"error": str(error)})
            return
        except OSError as error:
            self.send_json(500, {"error": f"Could not save marks: {error}"})
            return
        self.send_json(200, {"item": {
            "image_filename": filename,
            "enrollment_no": row.get("enrollment_no", ""),
            "subject_code": row.get("subject_code", ""),
            **{field: row.get(field, "") for field in MARK_FIELDS},
            "marks_status": row.get("marks_status", ""),
        }})

def main():
    parser = argparse.ArgumentParser(description="Serve the teacher portal.")
    parser.add_argument("--port", type=int, default=PORT, help="Port to serve portal on.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    args = parser.parse_args()

    os.chdir(DIRECTORY)
    # Enable address reuse so fast restarts work cleanly
    socketserver.TCPServer.allow_reuse_address = True
    
    server_port = args.port
    with socketserver.TCPServer((HOST, server_port), Handler) as httpd:
        url = f"http://localhost:{server_port}/index.html"
        print("=" * 60)
        print(" Sheet Data Extractor — Local Web Portal")
        print(f" Serving web app at: {url}")
        print(" Connecting to API at: http://localhost:8000")
        print(f" Press Ctrl+C to terminate.")
        print("=" * 60)
        
        # Open in default browser unless headless flag passed
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except OSError as error:
                print(f"Could not open browser automatically: {error}")
                
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            httpd.server_close()

if __name__ == "__main__":
    main()
