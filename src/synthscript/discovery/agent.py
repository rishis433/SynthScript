"""LLM-driven Discovery Agent for UI flow exploration."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from synthscript.adapters.base import SurfaceAdapter, SurfaceState
from synthscript.discovery.semantic_tree import SpatialSemanticTree, SemanticElement, ElementType
from synthscript.schema.models import ActionType, Locator, LocatorStrategy, Target, ResolutionStrategy
from synthscript.security.guard import SecurityGuard, IrreversibleActionError, SecurityPolicyViolation
from synthscript.security.redactor import PIIRedactor


class DiscoveryStepType(str, Enum):
    """Types of discovery steps."""

    OBSERVE = "observe"
    DECIDE = "decide"
    ACT = "act"


@dataclass
class DiscoveryStep:
    """A single step in the discovery process."""

    step_type: DiscoveryStepType
    timestamp: float
    state_snapshot: Optional[Dict[str, Any]] = None
    llm_decision: Optional[str] = None
    action_taken: Optional[str] = None
    element_targeted: Optional[Dict[str, Any]] = None
    input_value: Optional[str] = None
    reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_type": self.step_type.value,
            "timestamp": self.timestamp,
            "state_snapshot": self.state_snapshot,
            "llm_decision": self.llm_decision,
            "action_taken": self.action_taken,
            "element_targeted": self.element_targeted,
            "input_value": self.input_value,
            "reasoning": self.reasoning,
        }


@dataclass
class DiscoveryResult:
    """Result of the discovery process."""

    success: bool
    goal: str
    steps: List[DiscoveryStep] = field(default_factory=list)
    final_state: Optional[SurfaceState] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "final_state": {
                "url": self.final_state.url if self.final_state else None,
                "timestamp": self.final_state.timestamp if self.final_state else None,
            } if self.final_state else None,
            "error_message": self.error_message,
        }


class DiscoveryAgent:
    """LLM-driven agent for discovering UI flows."""

    def __init__(
        self,
        llm_provider: str = "openai",
        model: str = "gpt-4",
        max_steps: int = 20,
        api_key: Optional[str] = None,
        security_guard: Optional[SecurityGuard] = None,
        pii_redactor: Optional[PIIRedactor] = None,
    ):
        """Initialize the discovery agent.

        Args:
            llm_provider: LLM provider (openai, anthropic)
            model: Model name
            max_steps: Maximum number of steps to take
            api_key: API key for LLM provider
            security_guard: Security guard for policy enforcement
            pii_redactor: PII redactor for sensitive data
        """
        self.llm_provider = llm_provider
        self.model = model
        self.max_steps = max_steps
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.security_guard = security_guard or SecurityGuard()
        self.pii_redactor = pii_redactor or PIIRedactor()
        
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI library is required. Install with: pip install openai")
        
        if not self.api_key:
            raise ValueError("API key is required. Set OPENAI_API_KEY environment variable or pass api_key parameter")
        
        self.client = openai.OpenAI(api_key=self.api_key)
        self.semantic_tree = SpatialSemanticTree()

    async def discover(
        self,
        goal: str,
        adapter: SurfaceAdapter,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> DiscoveryResult:
        """Discover UI flow to achieve the given goal.

        Args:
            goal: The goal to achieve (e.g., "Search for member 12345")
            adapter: Surface adapter for interacting with UI
            initial_context: Initial context (e.g., input parameters)

        Returns:
            DiscoveryResult with steps taken
        """
        result = DiscoveryResult(success=False, goal=goal)
        steps_taken = 0
        
        try:
            # Check URL security policy
            if hasattr(adapter, '_page') and adapter._page:
                self.security_guard.check_url_allowed(adapter._page.url)
            
            # Initial observation
            current_state = await adapter.capture_state()
            result.final_state = current_state
            
            while steps_taken < self.max_steps:
                steps_taken += 1
                
                # Observe: Build semantic tree from current state
                self.semantic_tree.build_from_state(
                    current_state.accessibility_tree,
                    current_state.ocr_text,
                )
                
                observe_step = DiscoveryStep(
                    step_type=DiscoveryStepType.OBSERVE,
                    timestamp=current_state.timestamp,
                    state_snapshot=self.semantic_tree.to_dict(),
                )
                result.steps.append(observe_step)
                
                # Check if goal is achieved
                if self._check_goal_achieved(goal, current_state):
                    result.success = True
                    break
                
                # Decide: Use LLM to decide next action (with redacted state)
                decision = await self._llm_decide(goal, self.semantic_tree, initial_context)
                
                decide_step = DiscoveryStep(
                    step_type=DiscoveryStepType.DECIDE,
                    timestamp=current_state.timestamp,
                    llm_decision=decision.get("action"),
                    reasoning=decision.get("reasoning"),
                )
                result.steps.append(decide_step)
                
                # Check action security policy before executing
                action_description = decision.get("element", "")
                action_type = decision.get("action", "WAIT")
                try:
                    self.security_guard.check_action_allowed(
                        action_description,
                        action_type,
                        context={"goal": goal, "step": steps_taken}
                    )
                except IrreversibleActionError as e:
                    # In production, this would trigger a confirmation flow
                    # For now, we'll skip the action and continue
                    result.error_message = f"Irreversible action blocked: {e.reason}"
                    break
                except SecurityPolicyViolation as e:
                    result.error_message = f"Security policy violation: {e.message}"
                    break
                
                # Act: Execute the decided action
                action_result = await self._execute_action(
                    decision,
                    adapter,
                    initial_context,
                )
                
                act_step = DiscoveryStep(
                    step_type=DiscoveryStepType.ACT,
                    timestamp=current_state.timestamp,
                    action_taken=decision.get("action"),
                    element_targeted=decision.get("element"),
                    input_value=decision.get("input_value"),
                )
                result.steps.append(act_step)
                
                # Update state
                if action_result.new_state:
                    current_state = action_result.new_state
                    result.final_state = current_state
                
                # Check if action failed
                if not action_result.success:
                    result.error_message = action_result.error_message
                    break
                
                # Check if LLM says we're done
                if decision.get("done", False):
                    result.success = True
                    break
            
            return result
            
        except Exception as e:
            result.error_message = str(e)
            return result

    def _check_goal_achieved(self, goal: str, state: SurfaceState) -> bool:
        """Check if the goal has been achieved.

        Args:
            goal: The goal to check
            state: Current surface state

        Returns:
            True if goal achieved
        """
        # Simple heuristic: check if goal text appears in OCR or accessibility tree
        goal_lower = goal.lower()
        
        if state.ocr_text and goal_lower in state.ocr_text.lower():
            return True
        
        # Check accessibility tree for goal indicators
        if self._text_in_tree(state.accessibility_tree, goal_lower):
            return True
        
        return False

    def _text_in_tree(self, tree: Dict[str, Any], search_text: str) -> bool:
        """Recursively search for text in tree.

        Args:
            tree: Tree node
            search_text: Text to search for

        Returns:
            True if found
        """
        if not isinstance(tree, dict):
            return False
        
        for value in tree.values():
            if isinstance(value, str) and search_text in value.lower():
                return True
            if isinstance(value, dict) and self._text_in_tree(value, search_text):
                return True
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and self._text_in_tree(item, search_text):
                        return True
        
        return False

    async def _llm_decide(
        self,
        goal: str,
        semantic_tree: SpatialSemanticTree,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Use LLM to decide next action.

        Args:
            goal: Current goal
            semantic_tree: Current UI state
            context: Additional context

        Returns:
            Decision dictionary with action, element, input_value, reasoning, done
        """
        # Redact PII from semantic tree before sending to LLM
        redacted_tree_dict = self.pii_redactor.redact_dict(semantic_tree.to_dict())
        
        prompt = self._build_decision_prompt(goal, semantic_tree, context, redacted_tree_dict)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a UI automation expert. Decide the next action to achieve the goal. Respond in JSON format with keys: action (CLICK, TYPE_AND_ENTER, EXTRACT_TEXT, WAIT), element (description of target element), input_value (if needed), reasoning (why this action), done (boolean if goal achieved)."
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            
            decision_text = response.choices[0].message.content
            decision = json.loads(decision_text)
            
            # Validate decision structure
            required_keys = ["action", "reasoning", "done"]
            for key in required_keys:
                if key not in decision:
                    decision[key] = None
            
            return decision
            
        except Exception as e:
            # Fallback decision on LLM failure
            return {
                "action": "WAIT",
                "element": None,
                "input_value": None,
                "reasoning": f"LLM decision failed: {str(e)}",
                "done": False,
            }

    def _build_decision_prompt(
        self,
        goal: str,
        semantic_tree: SpatialSemanticTree,
        context: Optional[Dict[str, Any]] = None,
        redacted_tree_dict: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build prompt for LLM decision.

        Args:
            goal: Current goal
            semantic_tree: Current UI state
            context: Additional context
            redacted_tree_dict: Redacted tree dictionary for LLM

        Returns:
            Prompt string
        """
        # Use redacted tree for LLM to avoid sending PII
        tree_for_prompt = redacted_tree_dict if redacted_tree_dict else semantic_tree.to_dict()
        
        # Build LLM-friendly prompt from redacted tree
        prompt_parts = [
            f"Goal: {goal}",
            "",
            self._dict_to_llm_prompt(tree_for_prompt),
            "",
        ]
        
        if context:
            prompt_parts.append("Context:")
            prompt_parts.append(json.dumps(context, indent=2))
            prompt_parts.append("")
        
        prompt_parts.append("Decide the next action to achieve the goal.")
        
        return "\n".join(prompt_parts)

    def _dict_to_llm_prompt(self, tree_dict: Dict[str, Any]) -> str:
        """Convert dictionary to LLM-friendly prompt format.

        Args:
            tree_dict: Tree dictionary

        Returns:
            Formatted string
        """
        if not tree_dict:
            return "No UI elements detected."
        
        prompt_parts = ["Current UI State:"]
        
        elements = tree_dict.get("elements", [])
        for i, element in enumerate(elements, 1):
            element_desc = f"{i}. "
            
            if element.get("label"):
                element_desc += f"[{element['label']}] "
            
            element_desc += f"{element.get('type', 'unknown')}"
            
            if element.get("text"):
                element_desc += f": '{element['text']}'"
            
            if element.get("placeholder"):
                element_desc += f" (placeholder: '{element['placeholder']}')"
            
            if element.get("id"):
                element_desc += f" [id: {element['id']}]"
            
            if element.get("actionable"):
                element_desc += " [actionable]"
            
            prompt_parts.append(element_desc)
        
        return "\n".join(prompt_parts)

    async def _execute_action(
        self,
        decision: Dict[str, Any],
        adapter: SurfaceAdapter,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute the decided action.

        Args:
            decision: LLM decision
            adapter: Surface adapter
            context: Additional context

        Returns:
            Action execution result
        """
        action = decision.get("action", "WAIT")
        element_desc = decision.get("element")
        input_value = decision.get("input_value")
        
        # Build target from element description
        target = None
        if element_desc:
            target = self._build_target_from_description(element_desc)
        
        # Resolve input value from context if needed
        if input_value and context:
            input_value = self._resolve_input_value(input_value, context)
        
        # Execute action
        return await adapter.execute_action(
            action_type=action,
            target=target,
            input_value=input_value,
        )

    def _build_target_from_description(self, description: str) -> Dict[str, Any]:
        """Build target specification from element description.

        Args:
            description: Element description from LLM

        Returns:
            Target specification
        """
        # Try to find element by text in semantic tree
        element = self.semantic_tree.find_element_by_text(description)
        
        if element and element.id:
            # Use a11y_id strategy if we have an ID
            return {
                "locators": [
                    {
                        "strategy": "a11y_id",
                        "value": element.id,
                    }
                ],
                "resolution_strategy": "cascade",
            }
        
        # Fall back to OCR-relative strategy
        return {
            "locators": [
                {
                    "strategy": "ocr_relative",
                    "value": f"right of '{description}'",
                }
            ],
            "resolution_strategy": "cascade",
        }

    def _resolve_input_value(self, input_value: str, context: Dict[str, Any]) -> str:
        """Resolve input value from context.

        Args:
            input_value: Input value (may be a reference)
            context: Context dictionary

        Returns:
            Resolved value
        """
        if input_value.startswith("${") and input_value.endswith("}"):
            key = input_value[2:-1]
            return str(context.get(key, input_value))
        return input_value
