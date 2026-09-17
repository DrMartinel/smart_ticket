"""
The LLM seam. Nodes depend on `LLMClient`, never on `DefaultLLMClient` or a
LangChain type (ADR-0007). An ABC rather than a Protocol for the reason given
in `core/providers/base.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # llm.client subclasses LLMClient; a runtime import would cycle
    from ai_engine.core.llm.client import LLMResult


class LLMClient(ABC):
    @abstractmethod
    def complete(
        self, system_prompt: str, user_prompt: str, *, timeout: float | None = None
    ) -> LLMResult:
        """Implementations own circuit breaking, retry and fallback (spec
        §10.3) and signal exhaustion by RAISING CircuitOpenError or
        AllLLMDownError.

        Never return empty text: infer would blame the model and send
        the ticket to HITL under the wrong reason code.
        """
