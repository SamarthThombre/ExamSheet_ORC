# Frozen Test Set Acceptance Criteria Proposal

## 1. Executive Summary & Mathematical Calibration

The frozen test set contains **88 sheets** total:
- **Format A (`format_original`)**: 44 sheets
- **Format B (`format_v2`)**: 44 sheets

Because the test sample size is finite ($N=88$ pooled, $N=44$ per format), point estimates are subject to sampling variance. To ensure rigorous, pre-registered evaluation, we report both empirical point estimates and two-sided 95% Wilson score confidence intervals.

---

## 2. Wilson Score Interval Tables

### Table 1: Pooled Frozen Set ($N = 88$ sheets)

| Correct Count $k$ | Point Estimate | Wilson 95% CI (Lower, Upper) | Meets Point $\ge 95.0\%$? | Meets Lower Bound $\ge 90.0\%$? | Candidate Acceptance Tier |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 78 / 88 | 88.64% | [80.33%, 93.71%] | No | No | Fail |
| 79 / 88 | 89.77% | [81.69%, 94.53%] | No | No | Fail |
| 80 / 88 | 90.91% | [83.07%, 95.32%] | No | No | Fail |
| 81 / 88 | 92.05% | [84.48%, 96.09%] | No | No | Borderline |
| 82 / 88 | 93.18% | [85.91%, 96.84%] | No | No | Borderline |
| 83 / 88 | 94.32% | [87.38%, 97.55%] | No | No | Borderline |
| 84 / 88 | 95.45% | [88.89%, 98.22%] | **Yes** | No (88.89%) | Meets point only |
| **85 / 88** | **96.59%** | **[90.45%, 98.83%]** | **Yes** | **Yes** | **Acceptance Threshold (Min $\ge 90\%$ lower)** |
| 86 / 88 | 97.73% | [92.09%, 99.37%] | **Yes** | **Yes** | High Confidence Pass |
| 87 / 88 | 98.86% | [93.84%, 99.80%] | **Yes** | **Yes** | Exceptional Pass |
| 88 / 88 | 100.00% | [95.82%, 100.00%] | **Yes** | **Yes** | Perfect Score |

> **Key Takeaway for $N=88$**:
> - Point estimate $\ge 95.0\%$ requires at least **84/88** correct (allowing up to 4 errors).
> - Wilson 95% lower bound $\ge 90.0\%$ requires at least **85/88** correct (allowing at most 3 errors).

---

### Table 2: Per-Format Evaluation ($N = 44$ sheets each)

| Correct Count $k$ | Point Estimate | Wilson 95% CI (Lower, Upper) | Meets Point $\ge 95.0\%$? | Meets Lower Bound $\ge 90.0\%$? | Candidate Acceptance Tier |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 36 / 44 | 81.82% | [68.04%, 90.49%] | No | No | Fail |
| 37 / 44 | 84.09% | [70.63%, 92.07%] | No | No | Fail |
| 38 / 44 | 86.36% | [73.29%, 93.60%] | No | No | Fail |
| 39 / 44 | 88.64% | [76.02%, 95.05%] | No | No | Borderline |
| 40 / 44 | 90.91% | [78.84%, 96.41%] | No | No | Borderline |
| 41 / 44 | 93.18% | [81.77%, 97.65%] | No | No | Target Lower Bound ($\ge 80\%$) |
| 42 / 44 | 95.45% | [84.87%, 98.74%] | **Yes** | No (84.87%) | Meets point only |
| 43 / 44 | 97.73% | [88.19%, 99.60%] | **Yes** | No (88.19%) | High Confidence Pass |
| **44 / 44** | **100.00%** | **[91.97%, 100.00%]** | **Yes** | **Yes** | **Zero Error Pass (Only count with lower $\ge 90\%$)** |

> **Statistical Note for $N=44$**:
> Due to the small sample size ($N=44$), achieving a Wilson 95% lower bound $\ge 90.0\%$ mathematically requires **44/44 (100% exact match, zero errors)**. A single error (43/44) drops the lower bound to 88.19%.
> Therefore, for individual format splits, requiring a 90% lower bound is statistically over-restrictive. The recommended per-format threshold is:
> - Point estimate $\ge 93.0\%$ (allowing $\le 3$ errors out of 44, yielding Wilson lower bound $\ge 81.77\%$).

---

## 3. Proposed Acceptance Criteria for Human Review

The following criteria are proposed for official frozen-set acceptance verification:

### 1. Enrolment Recognition Accuracy
- **Pooled Tail-4 Exact Match ($N=88$)**:
  - Point Estimate: $\ge 95.0\%$
  - Wilson 95% CI Lower Bound: $\ge 90.0\%$
  - *Operational Rule*: Requires $\ge 85$ out of 88 sheets correct (at most 3 errors across the entire frozen test set).
- **Per-Format Tail-4 Exact Match ($N=44$ each)**:
  - Format A Point Estimate: $\ge 93.0\%$ ($\ge 41/44$ correct, Wilson lower bound $\ge 81.77\%$)
  - Format B Point Estimate: $\ge 93.0\%$ ($\ge 41/44$ correct, Wilson lower bound $\ge 81.77\%$)
  - Neither format may exhibit systemic collapse ($< 90.0\%$).

### 2. Format Identification
- **Overall Identification Accuracy**: $\ge 99.0\%$
- *Operational Rule*: At most 1 misidentified format across 88 sheets ($\ge 87/88 = 98.86\% \approx 99.0\%$, target 88/88 = 100.0%).

### 3. Teacher Workflow & Operational Safety
- **Rescan Rate on Clean Scans**: $\le 5.0\%$ ($\le 4$ clean sheets flagged `RESCAN_RECOMMENDED`).
- **Needs Review Rate**: $\le 15.0\%$ ($\le 13$ sheets routed to manual teacher verification).
- **Silent Error Rate (Critical Safety Metric)**: $\le 2.0\%$ (Target: **0 unflagged errors**).
  - Defined as: sheets where enrolment tail-4 did NOT match ground truth, but the system failed to trigger `RESCAN_RECOMMENDED` or `needs_review`.
  - Every recognition failure must be caught and routed to the teacher for manual review.

### 4. Subject Code Consensus
- **Mode A: Declared-Code Mode (Interactive / Batch-Declared)**:
  - Per-sheet agreement ratio: $\ge 98.0\%$.
  - False mismatch flags: **0** (the system must never flag a batch mismatch when the teacher declared the correct subject code).
- **Mode B: Undeclared Mode (Simulated Batches of 10 Sheets)**:
  - Across all simulated batches of 10 sheets: consensus must return either the true ground truth subject code or `UNDETERMINED`.
  - Wrong Code Consensus Rate: **0** (the system must NEVER output a conflicting/incorrect subject code).

### 5. Latency & Throughput (Single-Core CPU)
- **Mean End-to-End Latency**: $\le 600$ ms per sheet on 2000px canonical JPEGs.
- **95th Percentile Latency (P95)**: $\le 900$ ms per sheet.

---

## 4. Acceptance Criteria Summary Table

| Category | Metric | Evaluation Set | Target / Threshold | Pass / Fail Condition |
|:---|:---|:---|:---|:---|
| **Enrolment** | Tail-4 Exact Match (Pooled) | All 88 sheets | Point $\ge 95.0\%$, Wilson Lower $\ge 90.0\%$ | $\ge 85 / 88$ correct |
| **Enrolment** | Tail-4 Exact Match (Format A) | 44 sheets | Point $\ge 93.0\%$ | $\ge 41 / 44$ correct |
| **Enrolment** | Tail-4 Exact Match (Format B) | 44 sheets | Point $\ge 93.0\%$ | $\ge 41 / 44$ correct |
| **Format** | Format Identification Accuracy | All 88 sheets | Point $\ge 99.0\%$ | $\ge 87 / 88$ correct |
| **Safety** | Rescan Rate (Clean Scans) | All 88 sheets | Rate $\le 5.0\%$ | $\le 4 / 88$ flagged |
| **Safety** | Review Rate | All 88 sheets | Rate $\le 15.0\%$ | $\le 13 / 88$ reviewed |
| **Safety** | Silent Error Rate | All 88 sheets | Rate $\le 2.0\%$ | $\le 1$ (target 0) unflagged errors |
| **Subject Code** | Declared Mode Agreement | All 88 sheets | Agreement $\ge 98.0\%$, False Mismatch = 0 | 0 false mismatches |
| **Subject Code** | Undeclared Mode Batches | 9 batches of 10 | 0 wrong consensus codes | Correct or UNDETERMINED only |
| **Latency** | End-to-End per sheet | All 88 sheets | Mean $\le 600$ ms, P95 $\le 900$ ms | CPU execution limits |
