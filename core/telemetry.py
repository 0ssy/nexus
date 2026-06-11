import time
import json
import secrets
from typing import Optional

class TelemetrySystem:
    """
    Records every significant event in NEXUS for debugging and replay.
    Solves debugging chaos by making every run deterministic and traceable.
    
    Captures:
    - Every agent action with timing
    - Every decision point
    - Every error and recovery
    - Full replay snapshots
    - Performance metrics
    """
    def __init__(self):
        # run_id -> list of events
        self._runs: dict[str, list] = {}
        # room_id -> current run_id
        self._room_runs: dict[str, str] = {}
        # run_id -> metadata
        self._run_metadata: dict[str, dict] = {}
        # run_id -> performance metrics
        self._metrics: dict[str, dict] = {}

    def start_run(self, room_id: str, case_input: str) -> str:
        """Start a new telemetry run for a room. Returns run_id."""
        run_id = f"run_{secrets.token_hex(8)}"
        self._room_runs[room_id] = run_id
        self._runs[run_id] = []
        self._run_metadata[run_id] = {
            "run_id": run_id,
            "room_id": room_id,
            "case_input": case_input[:500],
            "started_at": time.time(),
            "completed_at": None,
            "status": "running",
            "total_events": 0,
            "error_count": 0,
            "agent_count": 0,
            "verdict_delivered": False
        }
        self._metrics[run_id] = {
            "agent_register_times": [],
            "message_post_times": [],
            "llm_call_times": [],
            "total_tokens_estimated": 0,
            "loops_blocked": 0,
            "messages_filtered": 0,
            "context_prunes": 0
        }

        self._record_event(run_id, "RUN_STARTED", "system", {
            "room_id": room_id,
            "case_preview": case_input[:200]
        })

        return run_id

    def get_run_id(self, room_id: str) -> Optional[str]:
        return self._room_runs.get(room_id)

    def _record_event(self, run_id: str, event_type: str,
                      agent_id: str, data: dict,
                      duration_ms: Optional[float] = None,
                      error: Optional[str] = None):
        if run_id not in self._runs:
            return

        event = {
            "id": f"evt_{secrets.token_hex(4)}",
            "run_id": run_id,
            "event_type": event_type,
            "agent_id": agent_id,
            "data": data,
            "timestamp": time.time(),
            "duration_ms": duration_ms,
            "error": error,
            "sequence": len(self._runs[run_id]) + 1
        }

        self._runs[run_id].append(event)
        self._run_metadata[run_id]["total_events"] += 1

        if error:
            self._run_metadata[run_id]["error_count"] += 1

    def record_agent_registered(self, room_id: str, agent_id: str,
                                 agent_name: str, skills: list,
                                 duration_ms: float = None):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._run_metadata[run_id]["agent_count"] += 1
        if duration_ms:
            self._metrics[run_id]["agent_register_times"].append(duration_ms)
        self._record_event(run_id, "AGENT_REGISTERED", agent_id, {
            "name": agent_name, "skills": skills
        }, duration_ms)

    def record_message(self, room_id: str, agent_id: str,
                       msg_type: str, content_preview: str,
                       quality_score: float = None,
                       duration_ms: float = None):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        if duration_ms:
            self._metrics[run_id]["message_post_times"].append(duration_ms)
        self._record_event(run_id, f"MESSAGE_{msg_type}", agent_id, {
            "content_preview": content_preview[:200],
            "quality_score": quality_score
        }, duration_ms)

    def record_loop_blocked(self, room_id: str, reason: str):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._metrics[run_id]["loops_blocked"] += 1
        self._record_event(run_id, "LOOP_BLOCKED", "system", {
            "reason": reason
        })

    def record_message_filtered(self, room_id: str, agent_id: str,
                                  reason: str, score: float):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._metrics[run_id]["messages_filtered"] += 1
        self._record_event(run_id, "MESSAGE_FILTERED", agent_id, {
            "reason": reason, "score": score
        })

    def record_context_pruned(self, room_id: str, pruned: int, tokens_saved: int):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._metrics[run_id]["context_prunes"] += 1
        self._record_event(run_id, "CONTEXT_PRUNED", "system", {
            "messages_pruned": pruned,
            "tokens_saved": tokens_saved
        })

    def record_verdict(self, room_id: str, agent_id: str,
                       confidence: float, duration_ms: float = None):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._run_metadata[run_id]["verdict_delivered"] = True
        self._record_event(run_id, "VERDICT_DELIVERED", agent_id, {
            "confidence": confidence
        }, duration_ms)

    def record_error(self, room_id: str, agent_id: str,
                     error: str, recovered: bool = False):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._record_event(run_id, "ERROR", agent_id, {
            "error": error, "recovered": recovered
        }, error=error)

    def complete_run(self, room_id: str, status: str = "completed"):
        run_id = self.get_run_id(room_id)
        if not run_id:
            return
        self._run_metadata[run_id]["completed_at"] = time.time()
        self._run_metadata[run_id]["status"] = status
        duration = (
            self._run_metadata[run_id]["completed_at"] -
            self._run_metadata[run_id]["started_at"]
        )
        self._run_metadata[run_id]["total_duration_seconds"] = round(duration, 2)
        self._record_event(run_id, "RUN_COMPLETED", "system", {
            "status": status,
            "duration_seconds": round(duration, 2)
        })

    def get_run_summary(self, run_id: str) -> dict:
        metadata = self._run_metadata.get(run_id, {})
        metrics = self._metrics.get(run_id, {})
        events = self._runs.get(run_id, [])

        avg_msg_time = (
            sum(metrics.get("message_post_times", [0])) /
            max(len(metrics.get("message_post_times", [])), 1)
        )

        return {
            **metadata,
            "metrics": {
                "avg_message_post_ms": round(avg_msg_time, 2),
                "loops_blocked": metrics.get("loops_blocked", 0),
                "messages_filtered": metrics.get("messages_filtered", 0),
                "context_prunes": metrics.get("context_prunes", 0),
                "total_events": len(events)
            },
            "event_timeline": [
                {
                    "sequence": e["sequence"],
                    "event_type": e["event_type"],
                    "agent_id": e["agent_id"],
                    "timestamp": e["timestamp"],
                    "duration_ms": e["duration_ms"],
                    "error": e["error"]
                }
                for e in events
            ]
        }

    def get_replay(self, run_id: str) -> list:
        """Returns full event log for replay and debugging."""
        return self._runs.get(run_id, [])

    def get_room_run_summary(self, room_id: str) -> Optional[dict]:
        run_id = self.get_run_id(room_id)
        if not run_id:
            return None
        return self.get_run_summary(run_id)

    def get_all_runs(self) -> list:
        return [
            {
                "run_id": run_id,
                "room_id": meta.get("room_id"),
                "status": meta.get("status"),
                "started_at": meta.get("started_at"),
                "verdict_delivered": meta.get("verdict_delivered"),
                "error_count": meta.get("error_count", 0),
                "total_events": meta.get("total_events", 0)
            }
            for run_id, meta in self._run_metadata.items()
        ]


# Global instance
telemetry = TelemetrySystem()