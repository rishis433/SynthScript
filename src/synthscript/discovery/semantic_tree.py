"""Spatial Semantic Tree for combining A11y and OCR data."""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict
from enum import Enum


class ElementType(str, Enum):
    """Types of UI elements."""

    BUTTON = "button"
    INPUT = "input"
    TEXT = "text"
    LINK = "link"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    UNKNOWN = "unknown"


@dataclass
class SemanticElement:
    """A semantic element in the UI."""

    element_type: ElementType
    text: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    position: Optional[Dict[str, int]] = None  # x, y, width, height
    actionable: bool = False
    children: List["SemanticElement"] = field(default_factory=list)
    ocr_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": self.element_type.value,
            "text": self.text,
            "label": self.label,
            "placeholder": self.placeholder,
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "actionable": self.actionable,
            "ocr_confidence": self.ocr_confidence,
            "children": [child.to_dict() for child in self.children],
        }


class SpatialSemanticTree:
    """Combines A11y tree and OCR data into a flattened semantic representation."""

    def __init__(self):
        """Initialize the spatial semantic tree."""
        self.root: Optional[SemanticElement] = None
        self.elements: List[SemanticElement] = []

    def build_from_state(
        self,
        accessibility_tree: Dict[str, Any],
        ocr_text: Optional[str] = None,
    ) -> SemanticElement:
        """Build semantic tree from accessibility tree and OCR text.

        Args:
            accessibility_tree: Playwright accessibility tree
            ocr_text: OCR-extracted text from screenshot

        Returns:
            Root semantic element
        """
        # Build from accessibility tree
        self.root = self._process_a11y_node(accessibility_tree)
        
        # Enhance with OCR data
        if ocr_text:
            self._enhance_with_ocr(ocr_text)
        
        # Flatten into list for easier LLM consumption
        self.elements = self._flatten_tree(self.root)
        
        return self.root

    def _process_a11y_node(self, node: Dict[str, Any]) -> SemanticElement:
        """Process a single accessibility node into semantic element.

        Args:
            node: Accessibility tree node

        Returns:
            Semantic element
        """
        role = node.get("role", "unknown")
        element_type = self._map_role_to_type(role)
        
        semantic_element = SemanticElement(
            element_type=element_type,
            text=node.get("name"),
            label=node.get("description"),
            id=node.get("id"),
            name=node.get("name"),
            actionable=self._is_actionable(role),
        )
        
        # Process children recursively
        if "children" in node and node["children"]:
            for child in node["children"]:
                if isinstance(child, dict):
                    semantic_element.children.append(self._process_a11y_node(child))
        
        return semantic_element

    def _map_role_to_type(self, role: str) -> ElementType:
        """Map accessibility role to element type.

        Args:
            role: Accessibility role

        Returns:
            Element type
        """
        role_lower = role.lower()
        
        if "button" in role_lower:
            return ElementType.BUTTON
        elif "textbox" in role_lower or "input" in role_lower:
            return ElementType.INPUT
        elif "link" in role_lower:
            return ElementType.LINK
        elif "combobox" in role_lower or "listbox" in role_lower:
            return ElementType.SELECT
        elif "checkbox" in role_lower:
            return ElementType.CHECKBOX
        elif "radio" in role_lower:
            return ElementType.RADIO
        elif "text" in role_lower:
            return ElementType.TEXT
        else:
            return ElementType.UNKNOWN

    def _is_actionable(self, role: str) -> bool:
        """Determine if element is actionable.

        Args:
            role: Accessibility role

        Returns:
            True if actionable
        """
        actionable_roles = [
            "button",
            "link",
            "textbox",
            "combobox",
            "checkbox",
            "radio",
            "input",
        ]
        return any(actionable in role.lower() for actionable in actionable_roles)

    def _enhance_with_ocr(self, ocr_text: str) -> None:
        """Enhance semantic tree with OCR-extracted text.

        Args:
            ocr_text: OCR-extracted text
        """
        # Split OCR text into lines and try to match with elements
        ocr_lines = [line.strip() for line in ocr_text.split("\n") if line.strip()]
        
        # This is a simple enhancement - in production, you'd use position data
        # to correlate OCR regions with specific elements
        for element in self.elements:
            if not element.text:
                # Try to find matching OCR text
                for line in ocr_lines:
                    if line and len(line) < 100:  # Reasonable text length
                        element.text = line
                        element.ocr_confidence = 0.8
                        break

    def _flatten_tree(self, node: SemanticElement) -> List[SemanticElement]:
        """Flatten semantic tree into list.

        Args:
            node: Root semantic element

        Returns:
            Flattened list of elements
        """
        elements = [node]
        for child in node.children:
            elements.extend(self._flatten_tree(child))
        return elements

    def to_llm_prompt(self) -> str:
        """Convert to LLM-friendly prompt format.

        Returns:
            Formatted string for LLM consumption
        """
        if not self.elements:
            return "No UI elements detected."
        
        prompt_parts = ["Current UI State:"]
        
        for i, element in enumerate(self.elements, 1):
            element_desc = f"{i}. "
            
            if element.label:
                element_desc += f"[{element.label}] "
            
            element_desc += f"{element.element_type.value}"
            
            if element.text:
                element_desc += f": '{element.text}'"
            
            if element.placeholder:
                element_desc += f" (placeholder: '{element.placeholder}')"
            
            if element.id:
                element_desc += f" [id: {element.id}]"
            
            if element.actionable:
                element_desc += " [actionable]"
            
            prompt_parts.append(element_desc)
        
        return "\n".join(prompt_parts)

    def find_actionable_elements(self) -> List[SemanticElement]:
        """Find all actionable elements.

        Returns:
            List of actionable elements
        """
        return [elem for elem in self.elements if elem.actionable]

    def find_element_by_text(self, text: str) -> Optional[SemanticElement]:
        """Find element by text content.

        Args:
            text: Text to search for

        Returns:
            Matching element or None
        """
        text_lower = text.lower()
        for element in self.elements:
            if element.text and text_lower in element.text.lower():
                return element
            if element.label and text_lower in element.label.lower():
                return element
        return None

    def find_element_by_id(self, element_id: str) -> Optional[SemanticElement]:
        """Find element by ID.

        Args:
            element_id: ID to search for

        Returns:
            Matching element or None
        """
        for element in self.elements:
            if element.id == element_id:
                return element
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire tree to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "root": self.root.to_dict() if self.root else None,
            "elements": [elem.to_dict() for elem in self.elements],
        }
