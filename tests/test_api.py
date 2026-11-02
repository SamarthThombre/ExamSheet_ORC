"""
API Test Suite & Regression Verification.
Tests:
  1. GET /health
  2. POST /predict (valid image)
  3. POST /predict (invalid extension -> 400)
  4. POST /predict (corrupt image data -> 422)
  5. POST /predict (missing file parameter -> 422)
  6. Regression verification between direct OCRService and FastAPI endpoint
"""

import sys
import json
from pathlib import Path
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.services.ocr_service import ocr_service


def run_all_tests():
    print("=" * 70)
    print("RUNNING FASTAPI TEST SUITE & REGRESSION VERIFICATION")
    print("=" * 70)

    with TestClient(app) as client:
        # Test 1: Health Check
        print("\n[TEST 1] GET /health")
        resp = client.get("/health")
        print(f"  Status Code: {resp.status_code}")
        print(f"  Response: {resp.json()}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data["status"] == "ok"
        assert data["ocr_loaded"] is True
        assert data["detector_loaded"] is True
        print("  -> PASSED: Health endpoint returned 200 OK with model readiness.")

        # Test 2: Valid Image Prediction
        test_img_path = PROJECT_ROOT / "data" / "raw" / "images" / "page_000001.png"
        print(f"\n[TEST 2] POST /predict with valid image: {test_img_path.name}")
        with open(test_img_path, "rb") as f:
            resp = client.post(
                "/predict",
                files={"file": (test_img_path.name, f, "image/png")},
            )
        print(f"  Status Code: {resp.status_code}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        res = resp.json()
        print(f"  Success: {res.get('success')}")
        print(f"  Result: {json.dumps(res.get('result'), indent=4)}")
        print(f"  Processing Time: {res.get('processing', {}).get('processing_time_ms')}ms")
        assert res["success"] is True
        assert res["result"]["rollno"] == "0801CA251001"
        assert res["result"]["subject_code"] == "CT10718"
        assert res["result"]["total_marks_corrected"] == 54
        assert res["result"]["needs_review"] is False
        print("  -> PASSED: Valid image extracted accurately with processing time metadata.")

        # Test 3: Invalid Extension (e.g. .txt)
        print("\n[TEST 3] POST /predict with invalid file extension (.txt)")
        resp = client.post(
            "/predict",
            files={"file": ("notes.txt", b"plain text content", "text/plain")},
        )
        print(f"  Status Code: {resp.status_code}")
        print(f"  Response: {resp.json()}")
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        err = resp.json()
        assert err["success"] is False
        assert err["error"]["code"] == "BAD_REQUEST"
        print("  -> PASSED: Invalid file extension rejected with 400 Bad Request.")

        # Test 4: Corrupt/Invalid Image Data
        print("\n[TEST 4] POST /predict with corrupted/non-image payload (.png)")
        resp = client.post(
            "/predict",
            files={"file": ("corrupt.png", b"this is not a valid png binary payload" * 10, "image/png")},
        )
        print(f"  Status Code: {resp.status_code}")
        print(f"  Response: {resp.json()}")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        err = resp.json()
        assert err["success"] is False
        assert err["error"]["code"] == "UNPROCESSABLE_IMAGE"
        print("  -> PASSED: Corrupted image rejected with 422 Unprocessable Entity.")

        # Test 5: Missing File Parameter
        print("\n[TEST 5] POST /predict without file parameter")
        resp = client.post("/predict", data={"other_param": "123"})
        print(f"  Status Code: {resp.status_code}")
        print(f"  Response: {resp.json()}")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        err = resp.json()
        assert err["success"] is False
        assert err["error"]["code"] == "VALIDATION_ERROR"
        print("  -> PASSED: Missing file parameter rejected with 422 Validation Error.")

        # Test 6: Regression Comparison on Benchmark Images
        print("\n" + "=" * 70)
        print("TEST 6: REGRESSION VERIFICATION (Direct OCRService vs. FastAPI /predict)")
        print("=" * 70)
        sample_pages = [
            "page_000001.png",
            "page_000004.png",
            "page_000005.png",
            "page_000012.png",
        ]

        all_matched = True
        for page_name in sample_pages:
            img_file = PROJECT_ROOT / "data" / "raw" / "images" / page_name
            assert img_file.exists(), f"Sample image {img_file} not found"

            # Direct Pipeline Inference
            direct_res = ocr_service.process_image(img_file)

            # FastAPI Endpoint Inference
            with open(img_file, "rb") as f:
                api_resp = client.post(
                    "/predict",
                    files={"file": (page_name, f, "image/png")},
                )
            assert api_resp.status_code == 200
            api_res = api_resp.json()["result"]

            # Field-by-field comparison
            fields_to_compare = [
                "rollno",
                "enrollment_no",
                "subject_code",
                "total_marks",
                "total_marks_corrected",
                "needs_review",
                "fusion_status",
            ]

            matches = {}
            page_ok = True
            for field in fields_to_compare:
                d_val = direct_res.get(field)
                a_val = api_res.get(field)
                is_eq = d_val == a_val
                matches[field] = is_eq
                if not is_eq:
                    page_ok = False
                    all_matched = False

            status_str = "MATCH" if page_ok else "MISMATCH"
            print(f"[{status_str}] {page_name}:")
            print(f"   Direct: rollno={direct_res.get('rollno')}, total_marks={direct_res.get('total_marks')}, corrected={direct_res.get('total_marks_corrected')}, needs_review={direct_res.get('needs_review')}")
            print(f"   API:    rollno={api_res.get('rollno')}, total_marks={api_res.get('total_marks')}, corrected={api_res.get('total_marks_corrected')}, needs_review={api_res.get('needs_review')}")

        assert all_matched, "Regression detected between Direct OCRService and FastAPI endpoint!"
        print("\n-> ALL REGRESSION TESTS PASSED: FastAPI outputs exactly match Direct OCRService (0 mismatches).")

    print("\n" + "=" * 70)
    print("ALL API AND REGRESSION TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
