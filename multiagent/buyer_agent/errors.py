"""Error codes and the one exception type. `str(err)` is the code only (no detail leaks)."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INPUT_INVALID = "INPUT_INVALID"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    SPLAT_UNREADABLE = "SPLAT_UNREADABLE"
    SCAN_TOO_SPARSE = "SCAN_TOO_SPARSE"
    IMAGE_INVALID = "IMAGE_INVALID"
    JEV_AUTH = "JEV_AUTH"
    JEV_RATE_LIMITED = "JEV_RATE_LIMITED"
    JEV_TIMEOUT = "JEV_TIMEOUT"
    JEV_BAD_RESPONSE = "JEV_BAD_RESPONSE"
    JEV_UNAVAILABLE = "JEV_UNAVAILABLE"
    INTERNAL = "INTERNAL"
    BUSY = "BUSY"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"


_VIEW = "One view couldn't be checked."
_RETRY_LATER = "We couldn't finish the check right now. Please try again in a minute."
_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INPUT_INVALID: "Something in the request was not valid. Please try again.",
    ErrorCode.FILE_NOT_FOUND: "We couldn't find one of the scans. Please rescan.",
    ErrorCode.SPLAT_UNREADABLE: "We couldn't read one of the 3D scans. Please rescan.",
    ErrorCode.SCAN_TOO_SPARSE: (
        "Your scan is too incomplete to compare. Walk all the way around the item and rescan."
    ),
    ErrorCode.IMAGE_INVALID: _VIEW,
    ErrorCode.JEV_AUTH: "The comparison service isn't set up correctly. We've been notified.",
    ErrorCode.JEV_RATE_LIMITED: _VIEW,
    ErrorCode.JEV_TIMEOUT: _VIEW,
    ErrorCode.JEV_BAD_RESPONSE: _VIEW,
    ErrorCode.JEV_UNAVAILABLE: _RETRY_LATER,
    ErrorCode.INTERNAL: "Something went wrong on our side. Please try again.",
    ErrorCode.BUSY: "Another check is running. Please try again in a moment.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please wait a bit and try again.",
    ErrorCode.BUDGET_EXHAUSTED: _RETRY_LATER,
    ErrorCode.ATTEMPTS_EXHAUSTED: "This item has been checked too many times. Please contact support.",
    ErrorCode.PAYLOAD_TOO_LARGE: "The request was too large. Please send less data.",
}


def user_message(code: ErrorCode | str) -> str:
    return _MESSAGES[ErrorCode(code)]


class AgentError(Exception):
    """`detail` is for the run log only; never put it in a response."""

    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(code.value)
        self.code = code
        self.detail = detail
