"""What the agent's own routes refuse, and the hand-off message each reason shows (F15)."""

from __future__ import annotations

from enum import StrEnum

from apps.accounts.models import Language
from apps.core.errors import CodedError
from apps.tickets.utils.router import ReasonCode
from infrastructure.dtos import AgentStopReason


class AgentRefusal(StrEnum):
    AGENT_OFF = "agent_off"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    CONVERSATION_ENDED = "conversation_ended"
    TURN_RUNNING = "turn_running"
    NOT_PENDING = "not_pending"
    TOOL_LIMIT = "agent_tool_limit"


class AgentError(CodedError):
    """An agent request core-api refuses."""

    code: AgentRefusal


STOP_REASONS = {
    AgentStopReason.STEP_LIMIT: ReasonCode.AGENT_STEP_LIMIT,
    AgentStopReason.TOOL_LIMIT: ReasonCode.AGENT_TOOL_LIMIT,
    AgentStopReason.BUDGET: ReasonCode.AGENT_BUDGET_EXCEEDED,
    AgentStopReason.TOOL_FAILED: ReasonCode.AGENT_TOOL_FAILED,
    AgentStopReason.TOOL_OUTCOME_UNKNOWN: ReasonCode.AGENT_TOOL_OUTCOME_UNKNOWN,
    AgentStopReason.INJECTION: ReasonCode.AGENT_INJECTION_DETECTED,
    AgentStopReason.INJECTION_IN_RESULT: ReasonCode.AGENT_INJECTION_IN_RESULT,
    AgentStopReason.MODEL_UNAVAILABLE: ReasonCode.AGENT_MODEL_UNAVAILABLE,
    AgentStopReason.SCHEMA_INVALID: ReasonCode.AGENT_SCHEMA_INVALID,
    AgentStopReason.TOKEN_REFUSED: ReasonCode.AGENT_TOKEN_REFUSED,
}

HANDOFF_TEXT: dict[ReasonCode, dict[Language, str]] = {
    ReasonCode.AGENT_STEP_LIMIT: {
        Language.EN: "I couldn't finish this in the steps one message allows.",
        Language.VI: "Em chưa xử lý xong yêu cầu này trong số bước cho phép của một tin nhắn.",
    },
    ReasonCode.AGENT_TOOL_LIMIT: {
        Language.EN: "This needed more actions than one message allows.",
        Language.VI: "Yêu cầu này cần nhiều thao tác hơn mức cho phép của một tin nhắn.",
    },
    ReasonCode.AGENT_BUDGET_EXCEEDED: {
        Language.EN: "This needed more work than one message allows.",
        Language.VI: "Yêu cầu này cần xử lý nhiều hơn mức cho phép của một tin nhắn.",
    },
    ReasonCode.AGENT_TOOL_FAILED: {
        Language.EN: "Something I needed to check didn't respond.",
        Language.VI: "Một hệ thống em cần kiểm tra không phản hồi.",
    },
    ReasonCode.AGENT_TOOL_OUTCOME_UNKNOWN: {
        Language.EN: (
            "I sent a change but didn't hear back, so I can't tell whether it was made. "
            "Please check before trying again."
        ),
        Language.VI: (
            "Em đã gửi một thay đổi nhưng không nhận được phản hồi, nên không biết thay đổi đã "
            "được thực hiện hay chưa. Vui lòng kiểm tra trước khi thử lại."
        ),
    },
    ReasonCode.AGENT_INJECTION_DETECTED: {
        Language.EN: "I can't act on this message. This conversation has ended.",
        Language.VI: "Em không thể xử lý tin nhắn này. Cuộc trò chuyện đã kết thúc.",
    },
    ReasonCode.AGENT_INJECTION_IN_RESULT: {
        Language.EN: "Something I read looked like instructions, so I stopped before changing anything.",
        Language.VI: (
            "Nội dung em vừa đọc có dạng mệnh lệnh, nên em đã dừng trước khi thay đổi gì."
        ),
    },
    ReasonCode.AGENT_MODEL_UNAVAILABLE: {
        Language.EN: "The assistant isn't available right now.",
        Language.VI: "Trợ lý hiện không khả dụng.",
    },
    ReasonCode.AGENT_SCHEMA_INVALID: {
        Language.EN: "I couldn't work out what to do with this.",
        Language.VI: "Em chưa xác định được cách xử lý yêu cầu này.",
    },
    ReasonCode.AGENT_TOKEN_REFUSED: {
        Language.EN: "Your sign-in ended, so I stopped. Nothing more was done.",
        Language.VI: "Phiên đăng nhập đã kết thúc nên em đã dừng. Không có thao tác nào thêm.",
    },
    ReasonCode.AGENT_MASK_FAILED: {
        Language.EN: (
            "I couldn't check this message for personal data, so I haven't read it. "
            "This conversation has ended."
        ),
        Language.VI: (
            "Em không kiểm tra được dữ liệu cá nhân trong tin nhắn này nên chưa đọc nó. "
            "Cuộc trò chuyện đã kết thúc."
        ),
    },
    ReasonCode.AGENT_ENGINE_UNAVAILABLE: {
        Language.EN: "The assistant isn't available right now.",
        Language.VI: "Trợ lý hiện không khả dụng.",
    },
}
