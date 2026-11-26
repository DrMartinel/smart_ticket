"""Free text read from the cloud and its observability, masked before it leaves core-api: text
whose masking failed, or that holds critical PII, is withheld (F17 BR-F17-06)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from asgiref.sync import async_to_sync
from django.conf import settings

from apps.tickets.domain.masking import mask_reply
from apps.tickets.domain.patterns import PIILevel

logger = logging.getLogger(__name__)

WITHHELD = "[withheld]"
_WITHHOLD = (PIILevel.MASK_FAILED, PIILevel.CRITICAL)


@dataclass(frozen=True)
class MaskedTexts:
    """Texts in the order given, each masked or withheld, and how many were withheld."""

    texts: list[str]
    withheld: int

    @classmethod
    def of(cls, texts: Sequence[str]) -> MaskedTexts:
        """Masks each distinct non-empty text once, with both tiers; none are quarantined."""
        distinct = sorted({t for t in texts if t})
        try:
            masked = dict(zip(distinct, async_to_sync(_mask_all)(distinct)))
        except Exception:
            logger.exception("infra: masking raised; withholding every text")
            masked = {}
        shown = [masked[t] if t in masked else WITHHELD if t else t for t in texts]
        return cls(shown, sum(1 for t in shown if t == WITHHELD))


async def _mask_all(texts: list[str]) -> list[str]:
    replies = await asyncio.gather(
        *(mask_reply(t, settings.THRESHOLDS.masking.ner_max_share, []) for t in texts)
    )
    return [WITHHELD if r.pii_level in _WITHHOLD else r.text_masked for r in replies]
