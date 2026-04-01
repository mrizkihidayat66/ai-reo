"""LLM-based intent classifier for routing user messages.

Uses a lightweight, constrained LLM call (max_tokens=5, temperature=0)
to classify user intent into one of four categories. This avoids sending
conversational messages through the full multi-agent analysis pipeline.
"""

import logging
from typing import Literal

from ai_reo.llm.providers import llm_manager

logger = logging.getLogger(__name__)

IntentType = Literal["ANALYSIS", "QUESTION", "CHAT", "COMMAND"]

CLASSIFIER_SYSTEM_PROMPT = """\
You are a router for an AI binary reverse engineering system called AI-REO.

Classify the user's message into exactly ONE of these categories:

- ANALYSIS: The user wants to analyze, examine, reverse engineer, decompile, debug, or understand a binary/executable/file. This includes CTF challenges, malware analysis, or any technical binary task.
- QUESTION: The user is asking a question about the system, its capabilities, reverse engineering concepts, or requesting information.
- CHAT: The user is making casual conversation, a greeting, or an off-topic remark.
- COMMAND: The user is issuing a direct system command (e.g., "pause", "stop", "export", "show results").

Respond with ONLY ONE WORD from the list above. No explanation, no punctuation.
"""


async def classify_user_intent(message: str) -> IntentType:
    """Classify user intent using a lightweight, constrained LLM call.

    Returns one of: ``ANALYSIS``, ``QUESTION``, ``CHAT``, ``COMMAND``.
    Falls back to ``ANALYSIS`` if classification fails.
    """
    try:
        provider = llm_manager.get_provider()
        response = await provider.chat_completion(
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            max_tokens=5,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip().upper()

        # Normalize — take only the first word in case the LLM adds fluff
        result = raw.split()[0] if raw else "ANALYSIS"

        if result in ("ANALYSIS", "QUESTION", "CHAT", "COMMAND"):
            logger.debug("Intent classification: %s → %s", message[:60], result)
            return result

        logger.debug("Unexpected classification '%s', defaulting to ANALYSIS", raw)
        return "ANALYSIS"

    except Exception as e:
        logger.warning("Intent classification failed: %s — defaulting to ANALYSIS", e)
        return "ANALYSIS"
