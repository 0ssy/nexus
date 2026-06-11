import time
import hashlib
from typing import Optional

class LoopDetector:
    """
    Detects and terminates infinite loops in NEXUS rooms.
    Watches for:
    - Agents repeating the same message content
    - Rooms exceeding maximum round limits
    - Conversations stuck without progress
    - Single agents dominating the conversation
    """
    def __init__(self):
        # room_id -> list of message fingerprints
        self._fingerprints: dict[str, list] = {}
        # room_id -> round count
        self._round_counts: dict[str, int] = {}
        # room_id -> agent message counts
        self._agent_counts: dict[str, dict] = {}
        # room_id -> last progress timestamp
        self._last_progress: dict[str, float] = {}
        # room_id -> terminated flag
        self._terminated: dict[str, bool] = {}
        # room_id -> termination reason
        self._termination_reasons: dict[str, str] = {}

        # Thresholds
        self.max_rounds = 10
        self.max_messages_per_agent = 5
        self.similarity_threshold = 0.85
        self.stall_timeout_seconds = 120
        self.max_total_messages = 50

    def _fingerprint(self, content: str) -> str:
        return hashlib.md5(content.strip().lower()[:200].encode()).hexdigest()

    def _similarity(self, fp1: str, fp2: str) -> float:
        matches = sum(c1 == c2 for c1, c2 in zip(fp1, fp2))
        return matches / max(len(fp1), len(fp2), 1)

    def register_room(self, room_id: str):
        self._fingerprints[room_id] = []
        self._round_counts[room_id] = 0
        self._agent_counts[room_id] = {}
        self._last_progress[room_id] = time.time()
        self._terminated[room_id] = False
        self._termination_reasons[room_id] = ""

    def is_terminated(self, room_id: str) -> bool:
        return self._terminated.get(room_id, False)

    def get_termination_reason(self, room_id: str) -> Optional[str]:
        return self._termination_reasons.get(room_id)

    def record_message(self, room_id: str, agent_id: str, content: str, msg_type: str) -> dict:
        """
        Record a message and check for loop conditions.
        Returns a result dict with should_terminate flag.
        """
        if self.is_terminated(room_id):
            return {
                "should_terminate": True,
                "reason": self._termination_reasons.get(room_id, "Room already terminated"),
                "loop_detected": True
            }

        if room_id not in self._fingerprints:
            self.register_room(room_id)

        # Track agent message count
        if agent_id not in self._agent_counts[room_id]:
            self._agent_counts[room_id][agent_id] = 0
        self._agent_counts[room_id][agent_id] += 1

        # Track rounds
        self._round_counts[room_id] += 1

        # Check 1 — max total messages
        if self._round_counts[room_id] > self.max_total_messages:
            return self._terminate(room_id, f"Maximum message limit ({self.max_total_messages}) reached")

        # Check 2 — max rounds
        if self._round_counts[room_id] > self.max_rounds and msg_type not in ["VERDICT", "SYSTEM"]:
            return self._terminate(room_id, f"Maximum rounds ({self.max_rounds}) reached without verdict")

        # Check 3 — single agent dominating
        agent_msg_count = self._agent_counts[room_id][agent_id]
        if agent_msg_count > self.max_messages_per_agent and msg_type not in ["VERDICT", "SYSTEM"]:
            return self._terminate(room_id, f"Agent {agent_id} exceeded message limit ({self.max_messages_per_agent})")

        # Check 4 — repeated content (semantic loop)
        content_fp = self._fingerprint(content)
        for existing_fp in self._fingerprints[room_id][-5:]:
            similarity = self._similarity(content_fp, existing_fp)
            if similarity >= self.similarity_threshold:
                return self._terminate(room_id, f"Repeated content detected — similarity {similarity:.0%}")

        # Check 5 — stall detection
        time_since_progress = time.time() - self._last_progress.get(room_id, time.time())
        if time_since_progress > self.stall_timeout_seconds:
            return self._terminate(room_id, f"Conversation stalled for {int(time_since_progress)}s")

        # All checks passed — record and continue
        self._fingerprints[room_id].append(content_fp)
        self._last_progress[room_id] = time.time()

        return {
            "should_terminate": False,
            "reason": None,
            "loop_detected": False,
            "round": self._round_counts[room_id],
            "agent_message_count": agent_msg_count
        }

    def _terminate(self, room_id: str, reason: str) -> dict:
        self._terminated[room_id] = True
        self._termination_reasons[room_id] = reason
        return {
            "should_terminate": True,
            "reason": reason,
            "loop_detected": True,
            "rounds_completed": self._round_counts.get(room_id, 0)
        }

    def mark_progress(self, room_id: str):
        """Call this when meaningful progress is made — resets stall timer."""
        self._last_progress[room_id] = time.time()

    def reset_room(self, room_id: str):
        """Reset loop detection for a room — used when verdict is delivered."""
        self._terminated[room_id] = False
        self._termination_reasons[room_id] = ""
        self._round_counts[room_id] = 0

    def get_stats(self, room_id: str) -> dict:
        return {
            "room_id": room_id,
            "rounds": self._round_counts.get(room_id, 0),
            "terminated": self._terminated.get(room_id, False),
            "termination_reason": self._termination_reasons.get(room_id),
            "agent_counts": self._agent_counts.get(room_id, {}),
            "loops_blocked": sum(
                1 for fp in self._fingerprints.get(room_id, [])
                if fp == self._fingerprint("")
            ),
            "time_since_progress": round(
                time.time() - self._last_progress.get(room_id, time.time()), 1
            )
        }

    def get_system_stats(self) -> dict:
        total_rooms = len(self._round_counts)
        terminated_rooms = sum(1 for v in self._terminated.values() if v)
        return {
            "total_rooms_monitored": total_rooms,
            "terminated_rooms": terminated_rooms,
            "active_rooms": total_rooms - terminated_rooms
        }


# Global instance
loop_detector = LoopDetector()