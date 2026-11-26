"""Refusal codes of the category endpoints, and the error that carries them."""

from __future__ import annotations

from enum import StrEnum

from apps.core.errors import CodedError


class CategoryRefusal(StrEnum):
    CATEGORY_NOT_FOUND = "category_not_found"
    NOT_ALLOWED = "not_allowed"
    REASON_REQUIRED = "reason_required"
    UNKNOWN_CATEGORY = "unknown_category"
    WORKFLOW_NOT_FOUND = "workflow_not_found"


class CategoryError(CodedError):
    """A category request core-api refuses (BR-X-08)."""
