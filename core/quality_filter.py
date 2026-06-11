import re
import time
from typing import Optional

class QualityFilter:
    """
    Filters low-quality messages from entering NEXUS rooms.
    Scores messages on:
    - Substance (does it add new information?)
    - Relevance (is it related to the case?)
    - Confidence (does the agent have a clear position?)
    - Verbosity penalty (excessive length without substance)
    - Repetition penalty (saying what was already said)
    """
    def __init__(self):
        # room_id -> list of approved message summaries
        self._approved_content: dict[str, list] = {}
        # room_id -> agent quality scores
        self._agent_scores: dict[str, dict] = {}
        # room_id -> blocked message count
        self._blocked_counts: dict[str, int] = {}
        # Thresholds
        self.min_quality_score = 0.4
        self.min_content_length = 50
        self.max_content_length = 8000
        self.verbosity_penalty_threshold = 3000
        # Message types that bypass quality filter
        self.bypass_types = ["VERDICT", "SYSTEM", "JOIN", "LEAVE", "RECRUIT"]

    def register_room(self, room_id: str):
        self._approved_content[room_id] = []
        self._agent_scores[room_id] = {}
        self._blocked_counts[room_id] = 0

    def _score_substance(self, content: str) -> float:
        """
        Score based on whether the message adds substance.
        Looks for concrete claims, numbers, recommendations.
        """
        score = 0.5
        # Positive signals
        if any(word in content.lower() for word in [
            "recommend", "advise", "suggest", "conclude", "evidence",
            "risk", "benefit", "cost", "legal", "financial", "therefore",
            "because", "however", "although", "specifically", "analysis"
        ]):
            score += 0.15
        # Numbers and specifics add substance
        if re.search(r'\d+', content):
            score += 0.1
        # Lists and structured content add substance
        if content.count('\n') > 2:
            score += 0.1
        # Hedging without substance reduces score
        hedge_count = sum(1 for word in [
            "maybe", "perhaps", "possibly", "might", "could be",
            "i think", "i believe", "not sure"
        ] if word in content.lower())
        score -= hedge_count * 0.05
        return min(max(score, 0.0), 1.0)

    def _score_relevance(self, content: str, room_context: Optional[str]) -> float:
        """Score based on relevance to the original case."""
        if not room_context:
            return 0.7
        context_words = set(room_context.lower().split())
        content_words = set(content.lower().split())
        if not context_words:
            return 0.7
        overlap = len(context_words & content_words)
        relevance = min(overlap / max(len(context_words), 1) * 3, 1.0)
        return max(relevance, 0.3)

    def _score_verbosity(self, content: str) -> float:
        """Penalize excessive length without added value."""
        length = len(content)
        if length < self.min_content_length:
            return 0.2
        if length > self.max_content_length:
            return 0.3
        if length > self.verbosity_penalty_threshold:
            # Penalize but don't eliminate
            excess = length - self.verbosity_penalty_threshold
            penalty = min(excess / self.verbosity_penalty_threshold * 0.3, 0.3)
            return 1.0 - penalty
        return 1.0

    def _score_repetition(self, content: str, room_id: str) -> float:
        """Penalize content that repeats what was already said."""
        approved = self._approved_content.get(room_id, [])
        if not approved:
            return 1.0
        content_words = set(content.lower().split())
        max_overlap = 0.0
        for prev_summary in approved[-5:]:
            prev_words = set(prev_summary.lower().split())
            if not prev_words:
                continue
            overlap = len(content_words & prev_words) / max(len(prev_words), 1)
            max_overlap = max(max_overlap, overlap)
        return 1.0 - (max_overlap * 0.5)

    def score_message(self, content: str, msg_type: str,
                      room_id: str, agent_id: str,
                      room_context: Optional[str] = None,
                      confidence: Optional[float] = None) -> dict:
        """
        Score a message and determine if it should be allowed.
        Returns scoring breakdown and allow/block decision.
        """
        if msg_type in self.bypass_types:
            return {
                "allowed": True,
                "score": 1.0,
                "reason": "Bypassed — system message type",
                "breakdown": {}
            }

        content_str = str(content)

        # Length check
        if len(content_str) < self.min_content_length:
            return {
                "allowed": False,
                "score": 0.0,
                "reason": f"Message too short (min {self.min_content_length} chars)",
                "breakdown": {}
            }

        # Score components
        substance = self._score_substance(content_str)
        relevance = self._score_relevance(content_str, room_context)
        verbosity = self._score_verbosity(content_str)
        repetition = self._score_repetition(content_str, room_id)

        # Confidence bonus
        confidence_bonus = 0.0
        if confidence is not None:
            confidence_bonus = (confidence - 0.5) * 0.2

        # Weighted final score
        final_score = (
            substance * 0.35 +
            relevance * 0.25 +
            verbosity * 0.25 +
            repetition * 0.15 +
            confidence_bonus
        )
        final_score = min(max(final_score, 0.0), 1.0)

        allowed = final_score >= self.min_quality_score

        # Track agent scores
        if room_id not in self._agent_scores:
            self._agent_scores[room_id] = {}
        if agent_id not in self._agent_scores[room_id]:
            self._agent_scores[room_id][agent_id] = []
        self._agent_scores[room_id][agent_id].append(final_score)

        if allowed:
            # Store summary for repetition detection
            summary = " ".join(content_str.split()[:50])
            self._approved_content[room_id] = self._approved_content.get(room_id, [])
            self._approved_content[room_id].append(summary)
        else:
            self._blocked_counts[room_id] = self._blocked_counts.get(room_id, 0) + 1

        return {
            "allowed": allowed,
            "score": round(final_score, 3),
            "reason": "Approved" if allowed else f"Quality score {final_score:.2f} below threshold {self.min_quality_score}",
            "breakdown": {
                "substance": round(substance, 3),
                "relevance": round(relevance, 3),
                "verbosity": round(verbosity, 3),
                "repetition": round(repetition, 3),
                "confidence_bonus": round(confidence_bonus, 3)
            }
        }

    def get_agent_quality(self, room_id: str, agent_id: str) -> dict:
        scores = self._agent_scores.get(room_id, {}).get(agent_id, [])
        if not scores:
            return {"agent_id": agent_id, "avg_score": None, "message_count": 0}
        return {
            "agent_id": agent_id,
            "avg_score": round(sum(scores) / len(scores), 3),
            "message_count": len(scores),
            "min_score": round(min(scores), 3),
            "max_score": round(max(scores), 3)
        }

    def get_room_stats(self, room_id: str) -> dict:
        agent_scores = self._agent_scores.get(room_id, {})
        all_scores = [s for scores in agent_scores.values() for s in scores]
        return {
            "room_id": room_id,
            "total_approved": len(self._approved_content.get(room_id, [])),
            "total_blocked": self._blocked_counts.get(room_id, 0),
            "avg_quality_score": round(sum(all_scores) / max(len(all_scores), 1), 3),
            "agent_quality": {
                agent_id: self.get_agent_quality(room_id, agent_id)
                for agent_id in agent_scores
            }
        }


# Global instance
quality_filter = QualityFilter()