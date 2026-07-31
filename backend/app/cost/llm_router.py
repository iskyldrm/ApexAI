"""LLM fallback router — ask a small model which tier to use.

Used only when heuristic + semantic disagree or both are uncertain.
Calls ``gpt-4o-mini`` (or the configured Tier-1 model) with a structured
prompt that returns one of: ``cheap``, ``standard``, ``premium``.

5-second timeout. Failure → returns ``Tier.STANDARD`` with reason='fallback'.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.cost.tiers import Tier, get_model_for_tier


logger = logging.getLogger(__name__)


@dataclass
class LLMRouterResult:
    """Result of an LLM-router classification."""

    tier: Tier
    confidence: float
    signals: dict = field(default_factory=dict)
    reason: str = ""


_CLASSIFY_PROMPT = """You are a cost-routing classifier. Given a user prompt, decide which model tier is needed:

- "cheap" — trivial lookup, formatting, short factual answer (gpt-4o-mini)
- "standard" — typical coding / editing / explanation task (gpt-4o)
- "premium" — design, architecture review, complex multi-step reasoning (claude-sonnet)

Respond with EXACTLY one word on a single line: cheap, standard, or premium.

Prompt:
\"\"\"
{prompt}
\"\"\"

Tier:"""


_TIER_FROM_WORD = {
    "cheap": Tier.CHEAP,
    "standard": Tier.STANDARD,
    "premium": Tier.PREMIUM,
    "1": Tier.CHEAP,
    "2": Tier.STANDARD,
    "3": Tier.PREMIUM,
}


class LLMRouter:
    """Use the Tier-1 LLM to classify prompts into tiers."""

    def __init__(self, completion_fn=None, timeout_seconds: float = 5.0) -> None:
        # Default to using the Tier-1 model via LiteLLMClient
        self._completion_fn = completion_fn
        self._timeout = timeout_seconds

    async def score(self, prompt: str) -> LLMRouterResult:
        """Call the small LLM and parse its tier word."""
        classify_prompt = _CLASSIFY_PROMPT.format(prompt=prompt[:2000])

        try:
            if self._completion_fn is None:
                from app.agent.llm.litellm_client import LiteLLMClient

                client = LiteLLMClient(cache=None)
                model = get_model_for_tier(Tier.CHEAP)
                response = await asyncio.wait_for(
                    client.completion(
                        model=model,
                        messages=[{"role": "user", "content": classify_prompt}],
                        tools=None,
                    ),
                    timeout=self._timeout,
                )
            else:
                response = await asyncio.wait_for(
                    self._completion_fn(classify_prompt),
                    timeout=self._timeout,
                )

            text = (response.content or "").strip().lower()
            # Take the first matching word
            for word in text.split():
                word = word.strip(".,;:!?\"'()")
                if word in _TIER_FROM_WORD:
                    tier = _TIER_FROM_WORD[word]
                    return LLMRouterResult(
                        tier=tier,
                        confidence=0.7,
                        signals={"raw_response": text[:200]},
                        reason=f"llm classifier → {word}",
                    )

            # No valid word found
            logger.warning("LLMRouter: no valid tier word in response: %r", text)
            return LLMRouterResult(
                tier=Tier.STANDARD,
                confidence=0.3,
                signals={"raw_response": text[:200], "parse_error": True},
                reason="llm parser failed → standard fallback",
            )

        except asyncio.TimeoutError:
            logger.warning("LLMRouter: timeout after %ss", self._timeout)
            return LLMRouterResult(
                tier=Tier.STANDARD,
                confidence=0.3,
                signals={"timeout": True},
                reason="llm router timeout → standard fallback",
            )
        except Exception as e:
            logger.warning("LLMRouter: %s", e)
            return LLMRouterResult(
                tier=Tier.STANDARD,
                confidence=0.3,
                signals={"error": str(e)[:200]},
                reason=f"llm router error → standard fallback",
            )