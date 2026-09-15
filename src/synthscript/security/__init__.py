"""Security guardrails and PII redaction for SynthScript."""

from .guard import SecurityGuard, IrreversibleActionError, SecurityPolicyViolation
from .redactor import PIIRedactor, PIIType, RedactionResult

__all__ = [
    "SecurityGuard",
    "IrreversibleActionError",
    "SecurityPolicyViolation",
    "PIIRedactor",
    "PIIType",
    "RedactionResult",
]
