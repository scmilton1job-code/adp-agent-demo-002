import csv
import io
import uuid
import logging
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools import transform_to_scim_format
from agent import agent

logger = logging.getLogger("adp-agent.batch")

# In-memory job store — survives the request lifecycle, resets on container restart.
# For a persistent demo swap this dict for a Redis or Firestore client.
_JOB_STORE: Dict[str, Dict[str, Any]] = {}


class BatchProcessingEngine:
    """
    Orchestrates bulk CSV uploads with non-blocking background execution.

    Jobs are keyed by a UUID and stored in _JOB_STORE so the caller can
    poll /invoke/batch-status/{job_id} instead of waiting on a single
    long-running HTTP request.
    """

    MAX_WORKERS = 4  # tune for Cloud Run vCPU allocation

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_csv_job(self, file_contents: bytes) -> str:
        """
        Parses the CSV, registers a job, kicks off background processing,
        and returns the job_id immediately.
        """
        job_id = str(uuid.uuid4())
        rows = self._parse_csv(file_contents)

        _JOB_STORE[job_id] = {
            "status": "running",
            "total": len(rows),
            "completed": 0,
            "provisioned": [],
            "blocked": [],
        }

        # Fire-and-forget via a daemon thread so FastAPI returns instantly.
        # In production replace with Cloud Tasks / Celery.
        import threading
        t = threading.Thread(target=self._run_job, args=(job_id, rows), daemon=True)
        t.start()

        logger.info("Batch job %s submitted — %d rows queued.", job_id, len(rows))
        return job_id

    def get_job_status(self, job_id: str) -> Dict[str, Any] | None:
        """Returns current job state, or None if the job_id is unknown."""
        return _JOB_STORE.get(job_id)

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _run_job(self, job_id: str, rows: list[dict]) -> None:
        """Processes all rows in parallel, updating the job store as results arrive."""
        job = _JOB_STORE[job_id]

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {
                pool.submit(self._process_row, row, idx): idx
                for idx, row in enumerate(rows, start=1)
            }
            for future in as_completed(futures):
                result = future.result()   # each _process_row returns a typed dict
                if result["outcome"] == "provisioned":
                    job["provisioned"].append(result["record"])
                else:
                    job["blocked"].append(result["record"])
                job["completed"] += 1

        job["status"] = "complete"
        job["metadata"] = {
            "total_records_evaluated": job["total"],
            "fully_provisioned_count": len(job["provisioned"]),
            "action_blocked_count": len(job["blocked"]),
        }
        logger.info(
            "Batch job %s finished — %d provisioned, %d blocked.",
            job_id,
            len(job["provisioned"]),
            len(job["blocked"]),
        )

    def _process_row(self, row: dict, row_number: int) -> dict:
        """Validates and classifies a single CSV row. Never raises — always returns."""
        record_id = row.get("id") or row.get("candidateId") or f"ROW-{row_number}"
        name_raw = row.get("name", "")
        first = row.get("firstName") or (name_raw.split()[0] if name_raw else "Candidate")
        last = row.get("lastName") or (name_raw.split()[-1] if name_raw else "Record")

        candidate_context = {
            "id": record_id,
            "firstName": first,
            "lastName": last,
            "email": row.get("email", ""),
            "department": row.get("department", ""),
            "jobTitle": row.get("jobTitle", ""),
            "startDate": row.get("startDate") or None,
        }

        try:
            result = agent.execute_reasoning(
                agent_mode="onboarding",
                data_context=candidate_context,
                user_prompt=f"Process batch row validation for id={record_id}",
            )

            if result.get("status") == "complete":
                scim_payload = transform_to_scim_format(candidate_context)
                return {
                    "outcome": "provisioned",
                    "record": {
                        "id": record_id,
                        "name": f"{first} {last}",
                        "scim": scim_payload,
                        "summary": result.get("validation_summary"),
                    },
                }
            else:
                return {
                    "outcome": "blocked",
                    "record": {
                        "id": record_id,
                        "name": f"{first} {last}",
                        "missing_fields": result.get("missing_fields", []),
                        "summary": result.get("validation_summary"),
                        "draft_remediation": result.get("remediation_draft", ""),
                    },
                }

        except Exception as exc:
            logger.error("Unhandled error on row %s: %s", record_id, exc)
            return {
                "outcome": "blocked",
                "record": {
                    "id": record_id,
                    "name": f"{first} {last}",
                    "missing_fields": ["system_error"],
                    "summary": f"Unhandled exception: {exc}",
                    "draft_remediation": "",
                },
            }

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------

    def _parse_csv(self, file_contents: bytes) -> list[dict]:
        stream = io.StringIO(file_contents.decode("utf-8"))
        return list(csv.DictReader(stream))


batch_engine = BatchProcessingEngine()
