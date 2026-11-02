# Release Checklist: Production Deployment

Before tagging and deploying a release, complete and verify every checklist item.

## 1. Codebase & Manifest Freeze
- [ ] Working tree is clean of temporary artifacts or uncommitted changes.
- [ ] Version number in `VERSION` and `app/config.py` is updated.
- [ ] Freeze manifest `manifest.json` is generated via `experiments/deploy2/make_manifest.py`.
- [ ] SHA-256 checksums match across all code, configs, models, and Dockerfile.
- [ ] Tamper detection test passes (modifying any byte triggers startup failure).

## 2. Regression & Baseline Verification
- [ ] 15-sheet identity test passes identically against DEPLOY-1 baseline.
- [ ] Format A tune regression meets baseline: enrolment tail-4 >= 99/102, cell exact >= 441/510.
- [ ] Format B tune regression meets baseline: enrolment tail-4 >= 94/101, cell exact >= 497/505.
- [ ] v3-DEV regression meets baseline: enrolment tail-4 >= 28/30, cell exact >= 127/150.
- [ ] Layout safety: zero wrong-layout sheets return values across color, grayscale, and b&w sets.
- [ ] Tilt safety: tilt rescan flag <= 3% on unperturbed originals; wrong unflagged <= 8% at all angles.

## 3. Security, Privacy & Compliance
- [ ] `scripts/check_imports.py` passes (0 forbidden cross-tier imports).
- [ ] `scripts/scan_outbound_network.py` passes (0 outbound calls; zero telemetry).
- [ ] Server log inspection verifies zero roll numbers, marks, subject codes, or original filenames in logs.
- [ ] Key management is admin-only; API keys stored as SHA-256 hashes (never plaintext).
- [ ] Free disk space check (> 500 MB) enforced on job submission.

## 4. Test Suite Execution
- [ ] `pytest tests_v2/` passes 100%.
- [ ] `pytest tests/ -m "not legacy"` passes 100%.
- [ ] `ENABLE_LEGACY=true pytest tests/ -m legacy` passes all 62 tests.
- [ ] CI script `python scripts/run_ci.py` passes with return code 0.

## 5. Operations & Disaster Recovery
- [ ] Database backup and restore to a fresh path tested and verified with `PRAGMA integrity_check`.
- [ ] Retention lifecycle purge tested with backdated job entries.
- [ ] Docker container build verified using Python 3.13 base image (`python:3.13-slim`).
