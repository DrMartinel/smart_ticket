"""
Response shapes for the few-shot pool endpoints (spec §3.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Schema


class FewshotExampleOut(Schema):
    id: int
    category: str
    input_text: str
    output_json: dict[str, Any]
    expires_at: datetime
