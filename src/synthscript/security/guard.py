"""Security guard for policy enforcement and irreversible action tracking."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set, Optional, Callable, Any
from urllib.parse import urlparse
import re


class SecurityPolicyViolation(Exception):
    """Raised when a security policy is violated."""

    def __init__(self, message: str, policy_type: str):
        self.message = message
        self.policy_type = policy_type
        super().__init__(f"{policy_type}: {message}")


class IrreversibleActionError(Exception):
    """Raised when an irreversible action requires confirmation."""

    def __init__(self, action: str, reason: str):
        self.action = action
        self.reason = reason
        super().__init__(f"Irreversible action '{action}' requires confirmation: {reason}")


class ActionRiskLevel(str, Enum):
    """Risk levels for actions."""

    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ActionPolicy:
    """Policy for a specific action."""

    action_pattern: str  # Regex pattern to match action descriptions
    risk_level: ActionRiskLevel
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    allowed_contexts: List[str] = field(default_factory=list)  # Contexts where this is allowed


@dataclass
class SecurityPolicy:
    """Overall security policy configuration."""

    allowed_domains: Set[str] = field(default_factory=set)
    allowed_url_patterns: List[str] = field(default_factory=list)
    blocked_domains: Set[str] = field(default_factory=set)
    action_policies: List[ActionPolicy] = field(default_factory=list)
    max_confirmation_wait_seconds: int = 300  # 5 minutes default


class SecurityGuard:
    """Security guard for enforcing policies and tracking irreversible actions."""

    def __init__(self, policy: Optional[SecurityPolicy] = None, max_confirmation_wait_seconds: int = 300):
        """Initialize the security guard.

        Args:
            policy: Security policy configuration
            max_confirmation_wait_seconds: Max wait for confirmations
        """
        self.policy = policy or self._default_policy()
        self.max_confirmation_wait_seconds = max_confirmation_wait_seconds
        self._pending_confirmations: dict[str, Any] = {}
        self._action_history: List[dict] = []

    def _default_policy(self) -> SecurityPolicy:
        """Create default security policy.

        Returns:
            Default security policy
        """
        return SecurityPolicy(
            allowed_domains={
                "localhost",
                "127.0.0.1",
                "localhost:5000",
                "127.0.0.1:5000",
            },
            action_policies=[
                # High-risk financial actions
                ActionPolicy(
                    action_pattern=r"(?i)(submit|confirm|execute).*(transfer|payment|withdrawal|delete)",
                    risk_level=ActionRiskLevel.CRITICAL,
                    requires_confirmation=True,
                    confirmation_message="This action will initiate a financial transaction. Confirm to proceed.",
                ),
                ActionPolicy(
                    action_pattern=r"(?i)(delete|remove|destroy).*(account|data|record)",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_confirmation=True,
                    confirmation_message="This action will permanently delete data. Confirm to proceed.",
                ),
                ActionPolicy(
                    action_pattern=r"(?i)(submit|confirm).*(order|purchase|buy)",
                    risk_level=ActionRiskLevel.HIGH,
                    requires_confirmation=True,
                    confirmation_message="This action will complete a purchase. Confirm to proceed.",
                ),
                # Moderate risk actions
                ActionPolicy(
                    action_pattern=r"(?i)(change|update).*(password|email|phone)",
                    risk_level=ActionRiskLevel.MODERATE,
                    requires_confirmation=True,
                    confirmation_message="This action will modify sensitive account information. Confirm to proceed.",
                ),
            ],
        )

    def check_url_allowed(self, url: str) -> bool:
        """Check if a URL is allowed by policy.

        Args:
            url: URL to check

        Returns:
            True if allowed, raises SecurityPolicyViolation otherwise
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Check blocked domains first
        if domain in self.policy.blocked_domains:
            raise SecurityPolicyViolation(
                f"Domain '{domain}' is blocked",
                "url_policy"
            )

        # Check allowed domains (strip port for comparison)
        domain_without_port = domain.split(":")[0] if ":" in domain else domain
        if self.policy.allowed_domains:
            # Check if domain (with or without port) is in allowlist
            domain_matches = (
                domain in self.policy.allowed_domains or
                domain_without_port in self.policy.allowed_domains
            )
            if not domain_matches:
                # Check URL patterns as fallback
                pattern_allowed = any(
                    re.match(pattern, url) for pattern in self.policy.allowed_url_patterns
                )
                if not pattern_allowed:
                    raise SecurityPolicyViolation(
                        f"Domain '{domain}' not in allowlist and no matching URL pattern",
                        "url_policy"
                    )

        return True

    def check_action_allowed(
        self,
        action_description: str,
        action_type: str,
        context: Optional[dict] = None,
    ) -> bool:
        """Check if an action is allowed by policy.

        Args:
            action_description: Description of the action
            action_type: Type of action (CLICK, TYPE_AND_ENTER, etc.)
            context: Additional context about the action

        Returns:
            True if allowed, raises exception otherwise
        """
        # Check against action policies
        for policy in self.policy.action_policies:
            if re.search(policy.action_pattern, action_description):
                # Check if context is allowed first
                if policy.allowed_contexts and context:
                    context_str = str(context).lower()
                    if not any(
                        allowed_ctx.lower() in context_str
                        for allowed_ctx in policy.allowed_contexts
                    ):
                        raise SecurityPolicyViolation(
                            f"Action not allowed in current context",
                            "action_policy"
                        )
                
                # Then check if confirmation is required
                if policy.requires_confirmation:
                    raise IrreversibleActionError(
                        action=action_description,
                        reason=policy.confirmation_message or "Action requires confirmation"
                    )

        # Log the action
        self._log_action(action_description, action_type, context)

        return True

    def confirm_action(self, action_id: str, confirmed: bool) -> None:
        """Confirm or reject a pending irreversible action.

        Args:
            action_id: ID of the pending action
            confirmed: Whether the action is confirmed

        Raises:
            ValueError: If action_id not found or already processed
        """
        if action_id not in self._pending_confirmations:
            raise ValueError(f"No pending confirmation for action ID: {action_id}")

        action_data = self._pending_confirmations.pop(action_id)

        if not confirmed:
            raise SecurityPolicyViolation(
                f"Action '{action_data['description']}' was rejected by user",
                "action_confirmation"
            )

    def request_confirmation(
        self,
        action_description: str,
        action_type: str,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """Request confirmation for an irreversible action.

        Args:
            action_description: Description of the action
            action_type: Type of action
            timeout_seconds: Timeout for confirmation (uses guard default if None)

        Returns:
            Action ID for confirmation tracking
        """
        import time
        import uuid

        action_id = str(uuid.uuid4())
        timeout = timeout_seconds or self.max_confirmation_wait_seconds

        self._pending_confirmations[action_id] = {
            "description": action_description,
            "action_type": action_type,
            "timestamp": time.time(),
            "timeout": timeout,
        }

        return action_id

    def get_pending_confirmation(self, action_id: str) -> Optional[dict]:
        """Get details of a pending confirmation.

        Args:
            action_id: ID of the pending action

        Returns:
            Action data if found, None otherwise
        """
        return self._pending_confirmations.get(action_id)

    def cleanup_expired_confirmations(self) -> int:
        """Clean up expired pending confirmations.

        Returns:
            Number of confirmations cleaned up
        """
        import time

        current_time = time.time()
        expired_ids = []

        for action_id, action_data in self._pending_confirmations.items():
            if current_time - action_data["timestamp"] > action_data["timeout"]:
                expired_ids.append(action_id)

        for action_id in expired_ids:
            del self._pending_confirmations[action_id]

        return len(expired_ids)

    def _log_action(self, description: str, action_type: str, context: Optional[dict]) -> None:
        """Log an action for audit trail.

        Args:
            description: Action description
            action_type: Action type
            context: Action context
        """
        import time

        self._action_history.append({
            "timestamp": time.time(),
            "description": description,
            "action_type": action_type,
            "context": context,
        })

    def get_action_history(self, limit: int = 100) -> List[dict]:
        """Get recent action history.

        Args:
            limit: Maximum number of actions to return

        Returns:
            List of recent actions
        """
        return self._action_history[-limit:]

    def add_allowed_domain(self, domain: str) -> None:
        """Add a domain to the allowlist.

        Args:
            domain: Domain to add
        """
        self.policy.allowed_domains.add(domain.lower())

    def add_blocked_domain(self, domain: str) -> None:
        """Add a domain to the blocklist.

        Args:
            domain: Domain to block
        """
        self.policy.blocked_domains.add(domain.lower())

    def add_action_policy(self, policy: ActionPolicy) -> None:
        """Add an action policy.

        Args:
            policy: Action policy to add
        """
        self.policy.action_policies.append(policy)

    def is_domain_allowed(self, domain: str) -> bool:
        """Check if a domain is allowed (without raising exception).

        Args:
            domain: Domain to check

        Returns:
            True if allowed, False otherwise
        """
        domain_lower = domain.lower()
        if domain_lower in self.policy.blocked_domains:
            return False
        if self.policy.allowed_domains and domain_lower not in self.policy.allowed_domains:
            return False
        return True
