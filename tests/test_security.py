"""Unit tests for security guardrails and PII redaction."""

import pytest
from unittest.mock import Mock
from pathlib import Path

from synthscript.security.guard import (
    SecurityGuard,
    SecurityPolicy,
    ActionPolicy,
    ActionRiskLevel,
    SecurityPolicyViolation,
    IrreversibleActionError,
)
from synthscript.security.redactor import (
    PIIRedactor,
    PIIPattern,
    PIIType,
    RedactionResult,
)


class TestSecurityGuard:
    """Tests for SecurityGuard."""

    def test_initialization(self):
        """Test guard initialization with default policy."""
        guard = SecurityGuard()
        
        assert guard.policy is not None
        assert "localhost" in guard.policy.allowed_domains
        assert len(guard.policy.action_policies) > 0

    def test_initialization_with_custom_policy(self):
        """Test guard initialization with custom policy."""
        custom_policy = SecurityPolicy(
            allowed_domains={"example.com"},
            blocked_domains={"malicious.com"},
        )
        guard = SecurityGuard(policy=custom_policy)
        
        assert guard.policy == custom_policy

    def test_check_url_allowed_default(self):
        """Test URL checking with default policy."""
        guard = SecurityGuard()
        
        # Should allow localhost
        assert guard.check_url_allowed("http://localhost:5000") is True
        assert guard.check_url_allowed("http://127.0.0.1:5000") is True

    def test_check_url_blocked_domain(self):
        """Test URL checking with blocked domain."""
        policy = SecurityPolicy(blocked_domains={"malicious.com"})
        guard = SecurityGuard(policy=policy)
        
        with pytest.raises(SecurityPolicyViolation, match="blocked"):
            guard.check_url_allowed("http://malicious.com")

    def test_check_url_not_in_allowlist(self):
        """Test URL checking with domain not in allowlist."""
        policy = SecurityPolicy(allowed_domains={"trusted.com"})
        guard = SecurityGuard(policy=policy)
        
        with pytest.raises(SecurityPolicyViolation, match="not in allowlist"):
            guard.check_url_allowed("http://untrusted.com")

    def test_check_url_pattern_allowed(self):
        """Test URL checking with pattern matching."""
        policy = SecurityPolicy(
            allowed_domains=set(),
            allowed_url_patterns=[r"http://internal\.example\.com/.*"],
        )
        guard = SecurityGuard(policy=policy)
        
        assert guard.check_url_allowed("http://internal.example.com/page") is True

    def test_check_action_allowed_safe(self):
        """Test action checking for safe actions."""
        guard = SecurityGuard()
        
        assert guard.check_action_allowed("Click button", "CLICK") is True

    def test_check_action_requires_confirmation(self):
        """Test action checking for irreversible actions."""
        guard = SecurityGuard()
        
        with pytest.raises(IrreversibleActionError, match="requires confirmation"):
            guard.check_action_allowed("Submit transfer", "CLICK")

    def test_check_action_context_restriction(self):
        """Test action checking with context restrictions."""
        policy = SecurityPolicy(
            action_policies=[
                ActionPolicy(
                    action_pattern=r"delete",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_confirmation=True,
                    allowed_contexts=["admin"],
                ),
            ]
        )
        guard = SecurityGuard(policy=policy)
        
        with pytest.raises(SecurityPolicyViolation, match="not allowed in current context"):
            guard.check_action_allowed("delete record", "CLICK", context={"role": "user"})

    def test_request_confirmation(self):
        """Test requesting confirmation for action."""
        guard = SecurityGuard()
        
        action_id = guard.request_confirmation("Submit transfer", "CLICK")
        
        assert action_id is not None
        assert len(action_id) > 0
        assert guard.get_pending_confirmation(action_id) is not None

    def test_confirm_action(self):
        """Test confirming an action."""
        guard = SecurityGuard()
        
        action_id = guard.request_confirmation("Submit transfer", "CLICK")
        
        # Confirm the action
        guard.confirm_action(action_id, confirmed=True)
        
        # Should be removed from pending
        assert guard.get_pending_confirmation(action_id) is None

    def test_confirm_action_rejected(self):
        """Test rejecting an action."""
        guard = SecurityGuard()
        
        action_id = guard.request_confirmation("Submit transfer", "CLICK")
        
        with pytest.raises(SecurityPolicyViolation, match="rejected"):
            guard.confirm_action(action_id, confirmed=False)

    def test_confirm_invalid_action_id(self):
        """Test confirming with invalid action ID."""
        guard = SecurityGuard()
        
        with pytest.raises(ValueError, match="No pending confirmation"):
            guard.confirm_action("invalid-id", confirmed=True)

    def test_cleanup_expired_confirmations(self):
        """Test cleanup of expired confirmations."""
        guard = SecurityGuard(max_confirmation_wait_seconds=0.01)
        
        action_id = guard.request_confirmation("Submit transfer", "CLICK")
        
        # Wait for expiration
        import time
        time.sleep(0.1)
        
        cleaned = guard.cleanup_expired_confirmations()
        
        assert cleaned >= 1
        assert guard.get_pending_confirmation(action_id) is None

    def test_action_history_logging(self):
        """Test action history logging."""
        guard = SecurityGuard()
        
        guard.check_action_allowed("Click button", "CLICK")
        
        history = guard.get_action_history()
        
        assert len(history) == 1
        assert history[0]["description"] == "Click button"

    def test_add_allowed_domain(self):
        """Test adding domain to allowlist."""
        guard = SecurityGuard()
        
        guard.add_allowed_domain("new-domain.com")
        
        assert "new-domain.com" in guard.policy.allowed_domains

    def test_add_blocked_domain(self):
        """Test adding domain to blocklist."""
        guard = SecurityGuard()
        
        guard.add_blocked_domain("malicious-site.com")
        
        assert "malicious-site.com" in guard.policy.blocked_domains

    def test_add_action_policy(self):
        """Test adding custom action policy."""
        guard = SecurityGuard()
        
        initial_count = len(guard.policy.action_policies)
        
        new_policy = ActionPolicy(
            action_pattern=r"custom action",
            risk_level=ActionRiskLevel.MODERATE,
        )
        guard.add_action_policy(new_policy)
        
        assert len(guard.policy.action_policies) == initial_count + 1

    def test_is_domain_allowed(self):
        """Test domain allowed check without exception."""
        guard = SecurityGuard()
        
        assert guard.is_domain_allowed("localhost") is True
        assert guard.is_domain_allowed("evil.com") is False


class TestPIIRedactor:
    """Tests for PIIRedactor."""

    def test_initialization(self):
        """Test redactor initialization."""
        redactor = PIIRedactor()
        
        assert len(redactor.patterns) > 0

    def test_initialization_with_custom_patterns(self):
        """Test redactor with custom patterns."""
        custom_patterns = [
            PIIPattern(
                pii_type=PIIType.CUSTOM,
                pattern=r"secret",
                replacement="[CUSTOM_REDACTED]",
            )
        ]
        redactor = PIIRedactor(custom_patterns=custom_patterns)
        
        assert len(redactor.patterns) > len(custom_patterns)

    def test_redact_ssn(self):
        """Test SSN redaction."""
        redactor = PIIRedactor()
        
        text = "My SSN is 123-45-6789"
        result = redactor.redact_text(text)
        
        assert "[SSN_REDACTED]" in result.redacted
        assert "123-45-6789" not in result.redacted
        assert result.pii_count == 1

    def test_redact_credit_card(self):
        """Test credit card redaction."""
        redactor = PIIRedactor()
        
        text = "Card number: 4111111111111111"
        result = redactor.redact_text(text)
        
        assert "[CARD_REDACTED]" in result.redacted
        assert result.pii_count >= 1

    def test_redact_email(self):
        """Test email redaction."""
        redactor = PIIRedactor()
        
        text = "Contact me at john@example.com"
        result = redactor.redact_text(text)
        
        assert "[EMAIL_REDACTED]" in result.redacted
        assert "john@example.com" not in result.redacted

    def test_redact_phone(self):
        """Test phone number redaction."""
        redactor = PIIRedactor()
        
        text = "Call me at (555) 123-4567"
        result = redactor.redact_text(text)
        
        assert "[PHONE_REDACTED]" in result.redacted
        assert "(555) 123-4567" not in result.redacted

    def test_redact_account_balance(self):
        """Test account balance redaction."""
        redactor = PIIRedactor()
        
        text = "Balance: $1,234.56"
        result = redactor.redact_text(text)
        
        assert "[BALANCE_REDACTED]" in result.redacted
        assert "$1,234.56" not in result.redacted

    def test_redact_dict(self):
        """Test redaction from dictionary."""
        redactor = PIIRedactor()
        
        data = {
            "name": "John Doe",
            "ssn": "123-45-6789",
            "email": "john@example.com",
        }
        
        redacted = redactor.redact_dict(data)
        
        assert redacted["name"] == "John Doe"
        assert "[SSN_REDACTED]" in redacted["ssn"]
        assert "[EMAIL_REDACTED]" in redacted["email"]

    def test_redact_list(self):
        """Test redaction from list."""
        redactor = PIIRedactor()
        
        data = ["John Doe", "123-45-6789", "john@example.com"]
        
        redacted = redactor.redact_list(data)
        
        assert redacted[0] == "John Doe"
        assert "[SSN_REDACTED]" in redacted[1]
        assert "[EMAIL_REDACTED]" in redacted[2]

    def test_redact_nested_structure(self):
        """Test redaction from nested structure."""
        redactor = PIIRedactor()
        
        data = {
            "user": {
                "name": "John",
                "contact": {
                    "email": "john@example.com",
                    "phone": "555-123-4567",
                },
            },
        }
        
        redacted = redactor.redact_dict(data)
        
        assert "[EMAIL_REDACTED]" in redacted["user"]["contact"]["email"]
        assert "[PHONE_REDACTED]" in redacted["user"]["contact"]["phone"]

    def test_redact_json(self):
        """Test redaction from JSON string."""
        redactor = PIIRedactor()
        
        json_str = '{"ssn": "123-45-6789", "email": "john@example.com"}'
        redacted = redactor.redact_json(json_str)
        
        assert "[SSN_REDACTED]" in redacted
        assert "[EMAIL_REDACTED]" in redacted

    def test_find_pii(self):
        """Test finding PII without redaction."""
        redactor = PIIRedactor()
        
        text = "SSN: 123-45-6789, Email: john@example.com"
        pii_found = redactor.find_pii(text)
        
        assert len(pii_found) == 2
        assert any(p["type"] == "ssn" for p in pii_found)
        assert any(p["type"] == "email" for p in pii_found)

    def test_has_pii(self):
        """Test checking if text contains PII."""
        redactor = PIIRedactor()
        
        assert redactor.has_pii("SSN: 123-45-6789") is True
        assert redactor.has_pii("Just regular text") is False

    def test_redaction_result_structure(self):
        """Test redaction result structure."""
        redactor = PIIRedactor()
        
        result = redactor.redact_text("SSN: 123-45-6789")
        
        assert result.original == "SSN: 123-45-6789"
        assert result.redacted != result.original
        assert result.pii_count == 1
        assert len(result.pii_found) == 1

    def test_add_pattern(self):
        """Test adding custom PII pattern."""
        redactor = PIIRedactor()
        
        initial_count = len(redactor.patterns)
        
        custom_pattern = PIIPattern(
            pii_type=PIIType.CUSTOM,
            pattern=r"TOKEN_[A-Z0-9]+",
            replacement="[TOKEN_REDACTED]",
        )
        redactor.add_pattern(custom_pattern)
        
        assert len(redactor.patterns) == initial_count + 1

    def test_remove_pattern(self):
        """Test removing PII pattern by type."""
        redactor = PIIRedactor()
        
        initial_count = len(redactor.patterns)
        
        redactor.remove_pattern(PIIType.SSN)
        
        assert len(redactor.patterns) == initial_count - 1
        assert not any(p.pii_type == PIIType.SSN for p in redactor.patterns)

    def test_get_patterns(self):
        """Test getting all patterns."""
        redactor = PIIRedactor()
        
        patterns = redactor.get_patterns()
        
        assert len(patterns) > 0
        assert isinstance(patterns, list)

    def test_redact_accessibility_tree(self):
        """Test redaction from accessibility tree."""
        redactor = PIIRedactor()
        
        tree = {
            "role": "WebArea",
            "name": "Page with SSN: 123-45-6789",
            "children": [
                {
                    "role": "textbox",
                    "name": "Email",
                    "value": "john@example.com",
                },
            ],
        }
        
        redacted = redactor.redact_accessibility_tree(tree)
        
        assert "[SSN_REDACTED]" in redacted["name"]
        assert "[EMAIL_REDACTED]" in redacted["children"][0]["value"]

    def test_redact_for_llm(self):
        """Test redaction for LLM consumption."""
        redactor = PIIRedactor()
        
        state = {
            "accessibility_tree": {
                "role": "WebArea",
                "name": "Account: SSN 123-45-6789",
            },
            "ocr_text": "Balance: $1,234.56",
        }
        
        redacted = redactor.redact_for_llm(state)
        
        assert "[SSN_REDACTED]" in redacted["accessibility_tree"]["name"]
        assert "[BALANCE_REDACTED]" in redacted["ocr_text"]

    def test_redact_screenshot(self, tmp_path):
        """Test screenshot redaction."""
        redactor = PIIRedactor()
        
        # Create a dummy image file
        input_path = tmp_path / "input.png"
        output_path = tmp_path / "output.png"
        input_path.write_bytes(b"dummy image data")
        
        # Redact (will copy if PIL not available)
        redactor.redact_screenshot(input_path, output_path)
        
        assert output_path.exists()

    def test_multiple_pii_types(self):
        """Test redaction of multiple PII types."""
        redactor = PIIRedactor()
        
        text = "SSN: 123-45-6789, Email: john@example.com, Phone: 555-123-4567"
        result = redactor.redact_text(text)
        
        assert result.pii_count == 3
        assert "[SSN_REDACTED]" in result.redacted
        assert "[EMAIL_REDACTED]" in result.redacted
        assert "[PHONE_REDACTED]" in result.redacted

    def test_no_pii_in_text(self):
        """Test redaction when no PII present."""
        redactor = PIIRedactor()
        
        text = "Just regular text without sensitive data"
        result = redactor.redact_text(text)
        
        assert result.redacted == text
        assert result.pii_count == 0
