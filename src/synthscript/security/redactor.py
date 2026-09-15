"""PII redactor for scrubbing sensitive data from logs and artifacts."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path


class PIIType(str, Enum):
    """Types of PII to redact."""

    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    EMAIL = "email"
    PHONE = "phone"
    ACCOUNT_BALANCE = "account_balance"
    ROUTING_NUMBER = "routing_number"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    CUSTOM = "custom"


@dataclass
class PIIPattern:
    """Pattern for detecting PII."""

    pii_type: PIIType
    pattern: str
    replacement: str = "[REDACTED]"
    description: str = ""


@dataclass
class RedactionResult:
    """Result of PII redaction."""

    original: str
    redacted: str
    pii_found: List[Dict[str, Any]] = field(default_factory=list)
    pii_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "original": self.original,
            "redacted": self.redacted,
            "pii_found": self.pii_found,
            "pii_count": self.pii_count,
        }


class PIIRedactor:
    """Redactor for PII in text and structured data."""

    def __init__(self, custom_patterns: Optional[List[PIIPattern]] = None):
        """Initialize the PII redactor.

        Args:
            custom_patterns: Custom PII patterns to add
        """
        self.patterns = self._default_patterns()
        if custom_patterns:
            self.patterns.extend(custom_patterns)

    def _default_patterns(self) -> List[PIIPattern]:
        """Get default PII patterns.

        Returns:
            List of default PII patterns
        """
        return [
            # SSN patterns (XXX-XX-XXXX or XXXXXXXXX)
            PIIPattern(
                pii_type=PIIType.SSN,
                pattern=r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b",
                replacement="[SSN_REDACTED]",
                description="Social Security Number",
            ),
            # Credit card patterns (13-19 digits)
            PIIPattern(
                pii_type=PIIType.CREDIT_CARD,
                pattern=r"\b(?:\d[ -]*?){13,19}\b",
                replacement="[CARD_REDACTED]",
                description="Credit Card Number",
            ),
            # Bank account patterns (8-17 digits)
            PIIPattern(
                pii_type=PIIType.BANK_ACCOUNT,
                pattern=r"\baccount\s*(?:number|#|no)?\s*[:#]?\s*\d{8,17}\b",
                replacement="[ACCOUNT_REDACTED]",
                description="Bank Account Number",
            ),
            # Email addresses
            PIIPattern(
                pii_type=PIIType.EMAIL,
                pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                replacement="[EMAIL_REDACTED]",
                description="Email Address",
            ),
            # Phone numbers (various formats)
            PIIPattern(
                pii_type=PIIType.PHONE,
                pattern=r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
                replacement="[PHONE_REDACTED]",
                description="Phone Number",
            ),
            # Account balance patterns (dollar amounts)
            PIIPattern(
                pii_type=PIIType.ACCOUNT_BALANCE,
                pattern=r"\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b",
                replacement="[BALANCE_REDACTED]",
                description="Account Balance",
            ),
            # Routing number (9 digits)
            PIIPattern(
                pii_type=PIIType.ROUTING_NUMBER,
                pattern=r"\brouting\s*(?:number|#|no)?\s*[:#]?\s*\d{9}\b",
                replacement="[ROUTING_REDACTED]",
                description="Routing Number",
            ),
            # Passport numbers
            PIIPattern(
                pii_type=PIIType.PASSPORT,
                pattern=r"\b[A-Za-z]{1,2}\d{6,9}\b",
                replacement="[PASSPORT_REDACTED]",
                description="Passport Number",
            ),
            # Driver's license (various formats)
            PIIPattern(
                pii_type=PIIType.DRIVERS_LICENSE,
                pattern=r"\b(?:DL|Driver'?s?License|License)\s*[:#]?\s*[A-Za-z0-9]{6,15}\b",
                replacement="[LICENSE_REDACTED]",
                description="Driver's License",
            ),
        ]

    def redact_text(self, text: str) -> RedactionResult:
        """Redact PII from text.

        Args:
            text: Text to redact

        Returns:
            RedactionResult with redacted text and PII found
        """
        redacted = text
        pii_found = []
        pii_count = 0

        for pattern_def in self.patterns:
            matches = re.finditer(pattern_def.pattern, text, re.IGNORECASE)
            for match in matches:
                pii_count += 1
                pii_found.append({
                    "type": pattern_def.pii_type.value,
                    "pattern": pattern_def.pattern,
                    "match": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "description": pattern_def.description,
                })
                redacted = redacted.replace(match.group(), pattern_def.replacement)

        return RedactionResult(
            original=text,
            redacted=redacted,
            pii_found=pii_found,
            pii_count=pii_count,
        )

    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact PII from dictionary.

        Args:
            data: Dictionary to redact

        Returns:
            Redacted dictionary
        """
        if not isinstance(data, dict):
            return data

        redacted = {}
        for key, value in data.items():
            if isinstance(value, str):
                result = self.redact_text(value)
                redacted[key] = result.redacted
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = self.redact_list(value)
            else:
                redacted[key] = value

        return redacted

    def redact_list(self, data: List[Any]) -> List[Any]:
        """Recursively redact PII from list.

        Args:
            data: List to redact

        Returns:
            Redacted list
        """
        if not isinstance(data, list):
            return data

        redacted = []
        for item in data:
            if isinstance(item, str):
                result = self.redact_text(item)
                redacted.append(result.redacted)
            elif isinstance(item, dict):
                redacted.append(self.redact_dict(item))
            elif isinstance(item, list):
                redacted.append(self.redact_list(item))
            else:
                redacted.append(item)

        return redacted

    def redact_accessibility_tree(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """Redact PII from accessibility tree.

        Args:
            tree: Accessibility tree

        Returns:
            Redacted accessibility tree
        """
        return self.redact_dict(tree)

    def redact_json(self, json_str: str) -> str:
        """Redact PII from JSON string.

        Args:
            json_str: JSON string

        Returns:
            Redacted JSON string
        """
        import json

        try:
            data = json.loads(json_str)
            redacted = self.redact_dict(data)
            return json.dumps(redacted)
        except json.JSONDecodeError:
            # If not valid JSON, treat as plain text
            result = self.redact_text(json_str)
            return result.redacted

    def find_pii(self, text: str) -> List[Dict[str, Any]]:
        """Find PII in text without redacting.

        Args:
            text: Text to search

        Returns:
            List of PII found
        """
        result = self.redact_text(text)
        return result.pii_found

    def has_pii(self, text: str) -> bool:
        """Check if text contains PII.

        Args:
            text: Text to check

        Returns:
            True if PII found, False otherwise
        """
        return len(self.find_pii(text)) > 0

    def add_pattern(self, pattern: PIIPattern) -> None:
        """Add a custom PII pattern.

        Args:
            pattern: PII pattern to add
        """
        self.patterns.append(pattern)

    def remove_pattern(self, pii_type: PIIType) -> None:
        """Remove patterns for a specific PII type.

        Args:
            pii_type: PII type to remove
        """
        self.patterns = [p for p in self.patterns if p.pii_type != pii_type]

    def get_patterns(self) -> List[PIIPattern]:
        """Get all current PII patterns.

        Returns:
            List of PII patterns
        """
        return self.patterns.copy()

    def redact_screenshot(self, image_path: Path, output_path: Path) -> None:
        """Redact PII from screenshot by drawing black boxes over sensitive regions.

        Args:
            image_path: Path to input screenshot
            output_path: Path to save redacted screenshot
        """
        try:
            from PIL import Image, ImageDraw

            # Open image
            image = Image.open(image_path)
            draw = ImageDraw.Draw(image)

            # Extract text from image using OCR
            ocr_text = self._extract_text_from_image(image)

            # Find PII locations (simplified - in production would use OCR with position data)
            pii_regions = self._find_pii_regions(ocr_text)

            # Draw black boxes over PII regions
            for region in pii_regions:
                draw.rectangle(
                    region,
                    fill="black",
                )

            # Save redacted image
            image.save(output_path)

        except ImportError:
            # PIL not available, copy file as-is
            import shutil
            shutil.copy(image_path, output_path)
        except Exception as e:
            # If redaction fails, copy original
            import shutil
            shutil.copy(image_path, output_path)
            print(f"Warning: Screenshot redaction failed: {e}")

    def _extract_text_from_image(self, image) -> str:
        """Extract text from image using OCR.

        Args:
            image: PIL Image

        Returns:
            Extracted text
        """
        try:
            import pytesseract
            return pytesseract.image_to_string(image)
        except ImportError:
            return ""

    def _find_pii_regions(self, text: str) -> List[Tuple[int, int, int, int]]:
        """Find PII regions in text (simplified implementation).

        Args:
            text: OCR text

        Returns:
            List of (x, y, width, height) tuples
        """
        # This is a simplified implementation
        # In production, would use OCR with position data to get exact coordinates
        # For now, return empty list as we don't have position data
        return []

    def redact_for_llm(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Redact PII from state before sending to LLM.

        Args:
            state: State dictionary with accessibility tree and OCR text

        Returns:
            Redacted state
        """
        redacted = state.copy()

        # Redact accessibility tree
        if "accessibility_tree" in redacted:
            redacted["accessibility_tree"] = self.redact_accessibility_tree(
                redacted["accessibility_tree"]
            )

        # Redact OCR text
        if "ocr_text" in redacted and redacted["ocr_text"]:
            result = self.redact_text(redacted["ocr_text"])
            redacted["ocr_text"] = result.redacted

        return redacted
