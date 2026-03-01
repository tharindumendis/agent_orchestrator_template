"""
core/job_logger.py
------------------
One log file per orchestration job.

Log structure:
  logs/jobs/
    YYYY-MM-DD_HH-MM-SS_<job_id>.log

Each file contains:
  - Job header  (ID, task, timestamps, agent name)
  - Numbered steps  (LLM thinking / tool calls / tool results / errors)
  - Job footer  (final answer, duration, SUCCESS or FAILED)

Usage:
    jl = JobLogger(task="research the topic", agent_name="OrchestratorAgent")
    jl.log_step("TOOL_CALL", "execute_task", details={"instruction": "..."})
    jl.log_step("TOOL_RESULT", "execute_task", output="...", success=True)
    jl.finish(final_answer="Done.", success=True)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Root logs directory (sits next to main.py)
_PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = _PROJECT_ROOT / "logs" / "jobs"

_log = logging.getLogger(__name__)


class JobLogger:
    """
    Creates and writes a structured per-job log file.

    Lifecycle:
        jl = JobLogger(task=..., agent_name=...)
        ... call jl.log_step() for each ReAct step ...
        jl.finish(final_answer=..., success=True/False)
    """

    def __init__(self, task: str, agent_name: str = "OrchestratorAgent") -> None:
        self.job_id: str = uuid.uuid4().hex[:8]
        self.task: str = task
        self.agent_name: str = agent_name
        self.started_at: datetime = datetime.now()
        self._step_counter: int = 0
        self._lines: list[str] = []

        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        ts = self.started_at.strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path: Path = LOGS_DIR / f"{ts}_{self.job_id}.log"

        self._write_header()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_step(
        self,
        step_type: str,
        title: str = "",
        details: dict | None = None,
        output: Any = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> None:
        self._step_counter += 1
        now = datetime.now()
        ts = now.strftime("%H:%M:%S.%f")[:-3]

        if success is True:
            badge = "[OK]     "
        elif success is False:
            badge = "[FAILED] "
        elif error:
            badge = "[ERROR]  "
        else:
            badge = "[INFO]   "

        block = [
            "",
            f"{'─' * 72}",
            f"STEP {self._step_counter:02d} | {ts} | {badge} {step_type.upper()}"
            + (f" | {title}" if title else ""),
            f"{'─' * 72}",
        ]

        if details:
            block.append("  INPUT:")
            for key, val in details.items():
                block.append(f"    {key}: {_pretty(val)}")

        if output is not None:
            block.append("  OUTPUT:")
            for line in _pretty(output).splitlines():
                block.append(f"    {line}")

        if error:
            block.append("  ERROR:")
            for line in str(error).splitlines():
                block.append(f"    {line}")

        self._append_lines(block)

    def finish(self, final_answer: Any = "", success: bool = True) -> None:
        ended_at = datetime.now()
        duration = (ended_at - self.started_at).total_seconds()
        status = "SUCCESS" if success else "FAILED"

        footer = [
            "",
            "=" * 72,
            "FINAL ANSWER:",
        ]
        ans_str = final_answer if isinstance(final_answer, str) else _pretty(final_answer)
        for line in (ans_str or "(no output)").splitlines():
            footer.append(f"  {line}")
        footer += [
            "",
            f"STATUS   : {status}",
            f"STEPS    : {self._step_counter}",
            f"DURATION : {duration:.2f}s",
            f"ENDED    : {ended_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 72,
        ]
        self._append_lines(footer)
        _log.info("Job %s %s | log: %s", self.job_id, status, self.log_path)

    @property
    def path(self) -> str:
        return str(self.log_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_header(self) -> None:
        header = [
            "=" * 72,
            "  ORCHESTRATOR AGENT JOB LOG",
            "=" * 72,
            f"  JOB ID  : {self.job_id}",
            f"  AGENT   : {self.agent_name}",
            f"  STARTED : {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  LOG     : {self.log_path.name}",
            "=" * 72,
            "",
            "  TASK:",
        ]
        for line in self.task.splitlines():
            header.append(f"    {line}")
        header.append("")
        self._append_lines(header)

    def _append_lines(self, lines: list[str]) -> None:
        self._lines.extend(lines)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            _log.error("Could not write to job log %s: %s", self.log_path, e)


def _pretty(value: Any) -> str:
    """Format a value as a readable string (JSON for dicts/lists, str otherwise)."""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)
