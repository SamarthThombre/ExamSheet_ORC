"""
app/metrics.py: Observability and Telemetry Engine.
Tracks request counts, endpoint latencies, active queue lengths, job statuses,
and OCR diagnostic flags.
Guaranteed to contain NO personal data (no student enrolments, marks, or filenames).
"""

import threading
import time
from typing import Dict, List, Any
import numpy as np


class MetricsTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.request_counts: Dict[str, int] = {}
        self.status_counts: Dict[int, int] = {}
        self.latencies_ms: List[float] = []
        self.flag_counts: Dict[str, int] = {}

    def record_request(self, endpoint: str, status_code: int, duration_ms: float):
        with self._lock:
            key = f"{endpoint}:{status_code}"
            self.request_counts[key] = self.request_counts.get(key, 0) + 1
            self.status_counts[status_code] = self.status_counts.get(status_code, 0) + 1
            self.latencies_ms.append(duration_ms)
            # Keep sliding window of latest 5000 requests
            if len(self.latencies_ms) > 5000:
                self.latencies_ms = self.latencies_ms[-5000:]

    def record_flag(self, flag_name: str):
        if not flag_name:
            return
        with self._lock:
            self.flag_counts[flag_name] = self.flag_counts.get(flag_name, 0) + 1

    def record_flags_batch(self, flags_list: List[str]):
        with self._lock:
            for fl in flags_list:
                if fl:
                    self.flag_counts[fl] = self.flag_counts.get(fl, 0) + 1

    def get_metrics_snapshot(self, queue_length: int = 0, jobs_by_status: Dict[str, int] = None) -> Dict[str, Any]:
        with self._lock:
            total_reqs = sum(self.status_counts.values())
            if self.latencies_ms:
                mean_lat = round(float(np.mean(self.latencies_ms)), 2)
                p95_lat = round(float(np.percentile(self.latencies_ms, 95)), 2)
            else:
                mean_lat = 0.0
                p95_lat = 0.0

            flags_copy = dict(self.flag_counts)
            reqs_copy = dict(self.request_counts)
            statuses_copy = dict(self.status_counts)

        return {
            "requests": {
                "total": total_reqs,
                "by_status": statuses_copy,
                "by_endpoint": reqs_copy,
                "latency_ms": {
                    "mean": mean_lat,
                    "p95": p95_lat,
                },
            },
            "jobs": {
                "queue_length": queue_length,
                "by_status": jobs_by_status or {"queued": 0, "processing": 0, "completed": 0, "failed": 0},
            },
            "flags": flags_copy,
            "contains_personal_data": False,
        }


metrics = MetricsTracker()
