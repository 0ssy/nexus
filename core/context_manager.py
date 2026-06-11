import json
import time
from typing import Optional

class ContextManager:
    """
    Manages context bloom in NEXUS rooms.
    Prevents token waste by pruning, summarizing,
    and compressing agent conversation history.
    """
    def __init__(self):
        # room_id -> list of messages
        self._message_cache: dict[str, list] = {}
        # room_id -> compressed summary
        self._summaries: dict[str, str] = {}
        # room_id -> token count estimate
        self._token_counts: dict[str, int] = {}
        # room_id -> original prompt
        self._original_prompts: dict[str, str] = {}

        # Thresholds
        self.max_messages_before_pruning = 20
        self.max_tokens_before_compression = 8000
        self.messages_to_keep_after_pruning = 8
        self.avg_tokens_per_char = 0.25

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) * self.avg_tokens_per_char)

    def register_room(self, room_id: str, original_prompt: str):
        self._original_prompts[room_id] = original_prompt
        self._message_cache[room_id] = []
        self._token_counts[room_id] = 0

    def add_message(self, room_id: str, message: dict):
        if room_id not in self._message_cache:
            self._message_cache[room_id] = []

        self._message_cache[room_id].append({
            **message,
            "added_at": time.time()
        })

        content_str = json.dumps(message.get("content", ""))
        self._token_counts[room_id] = self._token_counts.get(room_id, 0) + self.estimate_tokens(content_str)

    def needs_pruning(self, room_id: str) -> bool:
        messages = self._message_cache.get(room_id, [])
        tokens = self._token_counts.get(room_id, 0)
        return len(messages) > self.max_messages_before_pruning or tokens > self.max_tokens_before_compression

    def prune(self, room_id: str) -> dict:
        """
        Prune the message history for a room.
        Keeps: original prompt, VERDICT/SYSTEM messages, most recent messages.
        Removes: middle conversation that is no longer needed.
        """
        messages = self._message_cache.get(room_id, [])
        if not messages:
            return {"pruned": 0, "kept": 0, "tokens_saved": 0}

        original_count = len(messages)
        original_tokens = self._token_counts.get(room_id, 0)

        # Always keep VERDICT and SYSTEM messages
        critical = [m for m in messages if m.get("type") in ["VERDICT", "SYSTEM"]]

        # Keep most recent N messages
        recent = messages[-self.messages_to_keep_after_pruning:]

        # Merge without duplicates
        seen_ids = set()
        pruned_messages = []
        for m in critical + recent:
            msg_id = m.get("id", id(m))
            if msg_id not in seen_ids:
                seen_ids.add(msg_id)
                pruned_messages.append(m)

        self._message_cache[room_id] = pruned_messages

        # Recalculate token count
        new_tokens = sum(
            self.estimate_tokens(json.dumps(m.get("content", "")))
            for m in pruned_messages
        )
        self._token_counts[room_id] = new_tokens

        pruned_count = original_count - len(pruned_messages)
        tokens_saved = original_tokens - new_tokens

        return {
            "pruned": pruned_count,
            "kept": len(pruned_messages),
            "tokens_saved": tokens_saved
        }

    def get_focused_context(self, room_id: str, max_tokens: int = 4000) -> list:
        """
        Returns a focused, token-limited view of the conversation.
        Always includes the original prompt.
        Prioritizes VERDICT, POSITION, CHALLENGE messages.
        """
        messages = self._message_cache.get(room_id, [])
        original_prompt = self._original_prompts.get(room_id, "")

        # Priority order for message types
        priority = {
            "SYSTEM": 1,
            "VERDICT": 2,
            "CHALLENGE": 3,
            "POSITION": 4,
            "RESPONSE": 5,
        }

        sorted_messages = sorted(
            messages,
            key=lambda m: priority.get(m.get("type", ""), 99)
        )

        focused = []
        token_budget = max_tokens

        # Always inject original prompt first
        if original_prompt:
            prompt_tokens = self.estimate_tokens(original_prompt)
            if prompt_tokens < token_budget:
                focused.append({
                    "type": "SYSTEM",
                    "content": {"text": f"ORIGINAL CASE: {original_prompt}"},
                    "pinned": True
                })
                token_budget -= prompt_tokens

        # Fill remaining budget with prioritized messages
        for msg in sorted_messages:
            content_tokens = self.estimate_tokens(json.dumps(msg.get("content", "")))
            if content_tokens <= token_budget:
                focused.append(msg)
                token_budget -= content_tokens
            if token_budget <= 0:
                break

        return focused

    def get_summary(self, room_id: str) -> Optional[str]:
        return self._summaries.get(room_id)

    def set_summary(self, room_id: str, summary: str):
        self._summaries[room_id] = summary

    def get_stats(self, room_id: str) -> dict:
        messages = self._message_cache.get(room_id, [])
        return {
            "room_id": room_id,
            "message_count": len(messages),
            "estimated_tokens": self._token_counts.get(room_id, 0),
            "needs_pruning": self.needs_pruning(room_id),
            "has_summary": room_id in self._summaries,
            "original_prompt_set": room_id in self._original_prompts
        }

    def get_token_savings_report(self, room_id: str) -> dict:
        stats = self.get_stats(room_id)
        estimated_without_nexus = stats["estimated_tokens"] * 3
        return {
            "estimated_tokens_used": stats["estimated_tokens"],
            "estimated_tokens_without_nexus": estimated_without_nexus,
            "tokens_saved": estimated_without_nexus - stats["estimated_tokens"],
            "savings_percentage": round(
                ((estimated_without_nexus - stats["estimated_tokens"]) / max(estimated_without_nexus, 1)) * 100, 1
            )
        }


# Global instance
context_manager = ContextManager()