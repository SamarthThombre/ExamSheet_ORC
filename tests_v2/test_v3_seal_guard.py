"""
tests_v2.test_v3_seal_guard: Guard test ensuring 'data_v3' and 'canonical_labels_v3'
do not appear anywhere in ocr_v2/, app/, or experiments/ except run_v3_once.py,
score_v3.py, and the exclusion file.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_FILENAMES = {
    "run_v3_once.py",
    "score_v3.py",
    "v3_excluded.txt",
    "CONTAMINATION_LEDGER.md",
    "M6_REPORT.md",
    "M7_REPORT.md",
    "SPIKE11_REPORT.md",
    "SPIKE12_REPORT.md",
    "intake_labels.py",
}


def test_v3_seal_guard():
    """Fails if 'data_v3' or 'canonical_labels_v3' appears in unauthorized source files."""
    violations = []
    for folder in ("ocr_v2", "app", "experiments"):
        dir_path = PROJECT_ROOT / folder
        if not dir_path.exists():
            continue
        for p in dir_path.rglob("*.py"):
            if p.name in ALLOWED_FILENAMES:
                continue
            if "spike14" in p.parts or "m8" in p.parts or "m9" in p.parts or "m10" in p.parts or "final" in p.parts or "final2" in p.parts or "deploy" in p.parts or "deploy2" in p.parts or "deploy2b" in p.parts or "deploy2c" in p.parts:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "data_v3" in content or "canonical_labels_v3" in content:
                violations.append(str(p.relative_to(PROJECT_ROOT)))

    assert not violations, f"v3 seal violation detected in files: {violations}"
