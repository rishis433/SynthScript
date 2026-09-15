"""Artifact Compiler for converting discovery results to SynthScript artifacts."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from synthscript.schema.models import (
    SynthScriptArtifact,
    ArtifactMetadata,
    Contract,
    ParameterDefinition,
    StepAction,
    ActionType,
    Target,
    Locator,
    LocatorStrategy,
    ResolutionStrategy,
    BusinessException,
)
from synthscript.discovery.agent import DiscoveryResult, DiscoveryStep, DiscoveryStepType


class ArtifactCompiler:
    """Compiles discovery results into deterministic SynthScript artifacts."""

    def compile(
        self,
        discovery_result: DiscoveryResult,
        artifact_name: str,
        artifact_version: str = "1.0.0",
        target_surface: str = "web",
        input_parameters: Optional[Dict[str, Any]] = None,
        output_parameters: Optional[Dict[str, Any]] = None,
    ) -> SynthScriptArtifact:
        """Compile discovery result into SynthScript artifact.

        Args:
            discovery_result: Result from discovery agent
            artifact_name: Name for the artifact
            artifact_version: Version for the artifact
            target_surface: Target surface type
            input_parameters: Input parameter definitions
            output_parameters: Output parameter definitions

        Returns:
            SynthScriptArtifact
        """
        # Extract steps from discovery result
        flow_steps = self._extract_flow_steps(discovery_result)
        
        # Extract business exceptions if any occurred
        business_exceptions = self._extract_business_exceptions(discovery_result)
        
        # Build contract
        contract = self._build_contract(input_parameters, output_parameters)
        
        # Build metadata
        metadata = ArtifactMetadata(
            name=artifact_name,
            version=artifact_version,
            target_surface=target_surface,
            created_at=datetime.now(timezone.utc),
        )
        
        # Build artifact
        artifact = SynthScriptArtifact(
            metadata=metadata,
            contract=contract,
            flow=flow_steps,
            business_exceptions=business_exceptions,
        )
        
        return artifact

    def _extract_flow_steps(self, discovery_result: DiscoveryResult) -> List[StepAction]:
        """Extract flow steps from discovery result.

        Args:
            discovery_result: Discovery result

        Returns:
            List of StepAction objects
        """
        flow_steps = []
        step_counter = 0
        
        for discovery_step in discovery_result.steps:
            if discovery_step.step_type == DiscoveryStepType.ACT:
                step_counter += 1
                
                action_type = self._map_action_type(discovery_step.action_taken)
                
                # Build target from element targeted
                target = None
                if discovery_step.element_targeted:
                    target = self._build_target(discovery_step.element_targeted)
                
                # Create step action
                step_action = StepAction(
                    step_id=f"step_{step_counter}",
                    action_type=action_type,
                    target=target,
                    input_binding=None,  # Would be set based on context mapping
                    output_binding=None,  # Would be set for EXTRACT_TEXT actions
                    validation_rule=None,  # Could be enhanced to extract from reasoning
                )
                
                flow_steps.append(step_action)
        
        return flow_steps

    def _map_action_type(self, action: Optional[str]) -> ActionType:
        """Map string action to ActionType enum.

        Args:
            action: Action string

        Returns:
            ActionType
        """
        if not action:
            return ActionType.WAIT
        
        action_upper = action.upper()
        
        try:
            return ActionType(action_upper)
        except ValueError:
            # Default to WAIT for unknown actions
            return ActionType.WAIT

    def _build_target(self, element_targeted: Any) -> Optional[Target]:
        """Build target from element targeted during discovery.

        Args:
            element_targeted: Element information (dict or SemanticElement)

        Returns:
            Target object or None
        """
        if not element_targeted:
            return None
            
        # Extract locators from element
        locators = []
        
        # Handle both dict and SemanticElement objects
        if isinstance(element_targeted, dict):
            element_id = element_targeted.get("id")
            element_text = element_targeted.get("text")
        else:
            element_id = getattr(element_targeted, "id", None)
            element_text = getattr(element_targeted, "text", None)
        
        # Try to build an a11y_id locator if we have an ID
        if element_id:
            locators.append(
                Locator(
                    strategy=LocatorStrategy.A11Y_ID,
                    value=element_id,
                )
            )
        
        # Add OCR-relative locator as fallback
        if element_text:
            locators.append(
                Locator(
                    strategy=LocatorStrategy.OCR_RELATIVE,
                    value=f"right of '{element_text}'",
                )
            )
        
        # Add XPath locator as last resort
        element_xpath = element_targeted.get("xpath") if isinstance(element_targeted, dict) else None
        if element_xpath:
            locators.append(
                Locator(
                    strategy=LocatorStrategy.XPATH,
                    value=element_xpath,
                )
            )
        
        # If no locators, create a generic one
        if not locators:
            text = element_text or "element"
            locators.append(
                Locator(
                    strategy=LocatorStrategy.OCR_RELATIVE,
                    value=f"right of '{text}'",
                )
            )
        
        return Target(
            locators=locators,
            resolution_strategy=ResolutionStrategy.CASCADE,
        )

    def _extract_business_exceptions(
        self,
        discovery_result: DiscoveryResult,
    ) -> List[BusinessException]:
        """Extract business exceptions from discovery result.

        Args:
            discovery_result: Discovery result

        Returns:
            List of BusinessException objects
        """
        # For now, return empty list
        # In production, this would analyze error states encountered during discovery
        return []

    def _build_contract(
        self,
        input_parameters: Optional[Dict[str, Any]],
        output_parameters: Optional[Dict[str, Any]],
    ) -> Contract:
        """Build contract from parameters.

        Args:
            input_parameters: Input parameter definitions
            output_parameters: Output parameter definitions

        Returns:
            Contract object
        """
        input_defs = {}
        if input_parameters:
            for param_name, param_info in input_parameters.items():
                if isinstance(param_info, dict):
                    input_defs[param_name] = ParameterDefinition(
                        type=param_info.get("type", "string"),
                        required=param_info.get("required", True),
                        pii=param_info.get("pii", False),
                    )
                else:
                    input_defs[param_name] = ParameterDefinition(
                        type="string",
                        required=True,
                        pii=False,
                    )
        
        output_defs = {}
        if output_parameters:
            for param_name, param_info in output_parameters.items():
                if isinstance(param_info, dict):
                    output_defs[param_name] = ParameterDefinition(
                        type=param_info.get("type", "string"),
                        required=param_info.get("required", False),
                        pii=param_info.get("pii", False),
                    )
                else:
                    output_defs[param_name] = ParameterDefinition(
                        type="string",
                        required=False,
                        pii=False,
                    )
        
        return Contract(
            input_parameters=input_defs,
            output_parameters=output_defs,
        )

    def save_artifact(
        self,
        artifact: SynthScriptArtifact,
        output_path: str,
    ) -> None:
        """Save artifact to JSON file.

        Args:
            artifact: Artifact to save
            output_path: Path to save to
        """
        import json
        
        with open(output_path, "w") as f:
            json.dump(
                artifact.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )

    def load_artifact(self, input_path: str) -> SynthScriptArtifact:
        """Load artifact from JSON file.

        Args:
            input_path: Path to load from

        Returns:
            SynthScriptArtifact
        """
        import json
        
        with open(input_path, "r") as f:
            data = json.load(f)
        
        return SynthScriptArtifact(**data)
