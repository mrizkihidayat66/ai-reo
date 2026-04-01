"""Conversation Context management for tracking message history and tokens."""

from typing import Any, Dict, List, Optional
import tiktoken


class ConversationContext:
    """Manages chat history per agent/session to safely enforce token limits."""

    def __init__(self, session_id: str, max_tokens: int = 16000) -> None:
        self.session_id = session_id
        self.max_tokens = max_tokens
        self.messages: List[Dict[str, Any]] = []
        
        # litellm/openai specific tokenization
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = None

    def add_message(self, role: str, content: str) -> None:
        """Append a message to history and automatically truncate oldest context if limits exceeded."""
        self.messages.append({"role": role, "content": content})
        self.truncate_if_needed()

    def count_tokens(self, text: str) -> int:
        """Efficiently count tokens for standard text."""
        if self.encoding:
            return len(self.encoding.encode(text))
        # Fallback heuristic if tiktoken fails/unloaded
        return len(text.split()) * 2

    def get_total_tokens(self) -> int:
        """Calculate aggregate token size for the entire rolling window."""
        return sum(self.count_tokens(m.get("content", "")) for m in self.messages)

    def truncate_if_needed(self) -> None:
        """Intelligently prune old history to fit the context window, always preserving the System Prompt."""
        while self.get_total_tokens() > self.max_tokens and len(self.messages) > 2:
            # If the first message is a system prompt, keep it unconditionally to maintain instructions.
            # Pop the oldest user/assistant message right after it.
            if self.messages[0].get("role") == "system":
                self.messages.pop(1)
            else:
                self.messages.pop(0)

    def get_history(self) -> List[Dict[str, Any]]:
        """Retrieve the exact formatted chat history ready to pass to the LangChain/Litellm engine."""
        return self.messages

    def clear(self) -> None:
        """Reset conversation window."""
        self.messages.clear()
