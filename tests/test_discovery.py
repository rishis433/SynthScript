"""Unit tests for discovery components."""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from synthscript.discovery.semantic_tree import (
    SpatialSemanticTree,
    SemanticElement,
    ElementType,
)
from synthscript.discovery.compiler import ArtifactCompiler
from synthscript.discovery.agent import DiscoveryResult, DiscoveryStep, DiscoveryStepType
from synthscript.schema.models import (
    StepAction,
    ActionType,
    LocatorStrategy,
    ResolutionStrategy,
)
from synthscript.adapters.base import SurfaceState


class TestSpatialSemanticTree:
    """Tests for SpatialSemanticTree."""

    def test_initialization(self):
        """Test tree initialization."""
        tree = SpatialSemanticTree()
        assert tree.root is None
        assert tree.elements == []

    def test_build_from_simple_a11y_tree(self):
        """Test building tree from simple accessibility tree."""
        tree = SpatialSemanticTree()
        
        a11y_tree = {
            "role": "WebArea",
            "name": "Test Page",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                },
            ],
        }
        
        root = tree.build_from_state(a11y_tree)
        
        assert root is not None
        assert len(tree.elements) > 0
        assert root.element_type == ElementType.UNKNOWN  # WebArea maps to unknown

    def test_map_role_to_type(self):
        """Test role to element type mapping."""
        tree = SpatialSemanticTree()
        
        assert tree._map_role_to_type("button") == ElementType.BUTTON
        assert tree._map_role_to_type("textbox") == ElementType.INPUT
        assert tree._map_role_to_type("link") == ElementType.LINK
        assert tree._map_role_to_type("unknown") == ElementType.UNKNOWN

    def test_is_actionable(self):
        """Test actionable element detection."""
        tree = SpatialSemanticTree()
        
        assert tree._is_actionable("button") is True
        assert tree._is_actionable("textbox") is True
        assert tree._is_actionable("text") is False
        assert tree._is_actionable("unknown") is False

    def test_to_llm_prompt(self):
        """Test LLM prompt generation."""
        tree = SpatialSemanticTree()
        
        a11y_tree = {
            "role": "WebArea",
            "name": "Test",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                },
            ],
        }
        
        tree.build_from_state(a11y_tree)
        prompt = tree.to_llm_prompt()
        
        assert "Current UI State:" in prompt
        assert "button" in prompt.lower()

    def test_find_actionable_elements(self):
        """Test finding actionable elements."""
        tree = SpatialSemanticTree()
        
        a11y_tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                },
                {
                    "role": "text",
                    "name": "Label",
                },
            ],
        }
        
        tree.build_from_state(a11y_tree)
        actionable = tree.find_actionable_elements()
        
        assert len(actionable) == 1
        assert actionable[0].element_type == ElementType.BUTTON

    def test_find_element_by_text(self):
        """Test finding element by text."""
        tree = SpatialSemanticTree()
        
        a11y_tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                },
            ],
        }
        
        tree.build_from_state(a11y_tree)
        element = tree.find_element_by_text("Submit")
        
        assert element is not None
        assert element.text == "Submit"

    def test_enhance_with_ocr(self):
        """Test OCR enhancement."""
        tree = SpatialSemanticTree()
        
        a11y_tree = {
            "role": "WebArea",
            "children": [
                {
                    "role": "button",
                    "name": "",  # No text initially
                },
            ],
        }
        
        tree.build_from_state(a11y_tree, ocr_text="Submit Button")
        
        # OCR should have been processed
        # Check that elements were created
        assert len(tree.elements) > 0


class TestArtifactCompiler:
    """Tests for ArtifactCompiler."""

    @pytest.fixture
    def discovery_result(self):
        """Create a mock discovery result."""
        return DiscoveryResult(
            success=True,
            goal="Search for member",
            steps=[
                DiscoveryStep(
                    step_type=DiscoveryStepType.OBSERVE,
                    timestamp=0.0,
                ),
                DiscoveryStep(
                    step_type=DiscoveryStepType.DECIDE,
                    timestamp=1.0,
                    llm_decision="TYPE_AND_ENTER",
                ),
                DiscoveryStep(
                    step_type=DiscoveryStepType.ACT,
                    timestamp=2.0,
                    action_taken="TYPE_AND_ENTER",
                    element_targeted={"id": "input-field", "text": "Member ID"},
                    input_value="12345",
                ),
                DiscoveryStep(
                    step_type=DiscoveryStepType.ACT,
                    timestamp=3.0,
                    action_taken="CLICK",
                    element_targeted={"id": "submit-button", "text": "Submit"},
                ),
            ],
        )

    def test_initialization(self):
        """Test compiler initialization."""
        compiler = ArtifactCompiler()
        assert compiler is not None

    def test_compile_basic_artifact(self, discovery_result):
        """Test compiling basic artifact."""
        compiler = ArtifactCompiler()
        
        artifact = compiler.compile(
            discovery_result=discovery_result,
            artifact_name="test_flow",
            artifact_version="1.0.0",
            target_surface="web",
        )
        
        assert artifact.metadata.name == "test_flow"
        assert artifact.metadata.version == "1.0.0"
        assert len(artifact.flow) == 2  # Two ACT steps

    def test_compile_with_parameters(self, discovery_result):
        """Test compiling with input/output parameters."""
        compiler = ArtifactCompiler()
        
        input_params = {
            "member_id": {"type": "string", "required": True, "pii": False}
        }
        output_params = {
            "result": {"type": "string", "required": False}
        }
        
        artifact = compiler.compile(
            discovery_result=discovery_result,
            artifact_name="test_flow",
            input_parameters=input_params,
            output_parameters=output_params,
        )
        
        assert "member_id" in artifact.contract.input_parameters
        assert "result" in artifact.contract.output_parameters
        assert artifact.contract.input_parameters["member_id"].required is True

    def test_extract_flow_steps(self, discovery_result):
        """Test flow step extraction."""
        compiler = ArtifactCompiler()
        
        steps = compiler._extract_flow_steps(discovery_result)
        
        assert len(steps) == 2
        assert steps[0].action_type == ActionType.TYPE_AND_ENTER
        assert steps[1].action_type == ActionType.CLICK

    def test_map_action_type(self):
        """Test action type mapping."""
        compiler = ArtifactCompiler()
        
        assert compiler._map_action_type("CLICK") == ActionType.CLICK
        assert compiler._map_action_type("TYPE_AND_ENTER") == ActionType.TYPE_AND_ENTER
        assert compiler._map_action_type("WAIT") == ActionType.WAIT
        assert compiler._map_action_type("UNKNOWN") == ActionType.WAIT  # Default

    def test_build_target_with_id(self):
        """Test building target with element ID."""
        compiler = ArtifactCompiler()
        
        element = {"id": "test-id", "text": "Test"}
        target = compiler._build_target(element)
        
        assert target is not None
        assert len(target.locators) >= 1
        assert target.locators[0].strategy == LocatorStrategy.A11Y_ID
        assert target.locators[0].value == "test-id"

    def test_build_target_without_id(self):
        """Test building target without element ID."""
        compiler = ArtifactCompiler()
        
        element = {"text": "Test Button"}
        target = compiler._build_target(element)
        
        assert target is not None
        assert len(target.locators) >= 1
        assert target.locators[0].strategy == LocatorStrategy.OCR_RELATIVE

    def test_build_target_with_none(self):
        """Test building target with None."""
        compiler = ArtifactCompiler()
        
        target = compiler._build_target(None)
        
        assert target is None

    def test_build_contract(self):
        """Test contract building."""
        compiler = ArtifactCompiler()
        
        input_params = {"test": {"type": "string", "required": True}}
        output_params = {"result": {"type": "string", "required": False}}
        
        contract = compiler._build_contract(input_params, output_params)
        
        assert "test" in contract.input_parameters
        assert "result" in contract.output_parameters

    def test_save_and_load_artifact(self, discovery_result, tmp_path):
        """Test saving and loading artifact."""
        compiler = ArtifactCompiler()
        
        artifact = compiler.compile(
            discovery_result=discovery_result,
            artifact_name="test_flow",
        )
        
        # Save
        artifact_path = tmp_path / "artifact.json"
        compiler.save_artifact(artifact, str(artifact_path))
        
        assert artifact_path.exists()
        
        # Load
        loaded_artifact = compiler.load_artifact(str(artifact_path))
        
        assert loaded_artifact.metadata.name == artifact.metadata.name
        assert len(loaded_artifact.flow) == len(artifact.flow)


class TestDiscoveryAgent:
    """Tests for DiscoveryAgent (without real LLM calls)."""

    @patch("synthscript.discovery.agent.OPENAI_AVAILABLE", True)
    @patch.dict("sys.modules", {"openai": Mock()})
    def test_initialization_without_api_key(self):
        """Test initialization fails without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key is required"):
                from synthscript.discovery.agent import DiscoveryAgent
                DiscoveryAgent(api_key=None)

    def test_check_goal_achieved_with_ocr(self):
        """Test goal achievement check with OCR."""
        from synthscript.discovery.agent import DiscoveryAgent
        
        # Test the helper method directly without full initialization
        agent = object.__new__(DiscoveryAgent)
        
        state = SurfaceState(
            accessibility_tree={},
            ocr_text="Member found: 12345",
            timestamp=0.0,
        )
        
        assert agent._check_goal_achieved("12345", state) is True
        assert agent._check_goal_achieved("999", state) is False

    def test_text_in_tree(self):
        """Test recursive text search in tree."""
        from synthscript.discovery.agent import DiscoveryAgent
        
        # Test the helper method directly without full initialization
        agent = object.__new__(DiscoveryAgent)
        
        tree = {
            "role": "WebArea",
            "name": "Test",
            "children": [
                {
                    "role": "button",
                    "name": "Submit",
                },
            ],
        }
        
        assert agent._text_in_tree(tree, "submit") is True
        assert agent._text_in_tree(tree, "cancel") is False

    def test_resolve_input_value(self):
        """Test input value resolution."""
        from synthscript.discovery.agent import DiscoveryAgent
        
        # Test the helper method directly without full initialization
        agent = object.__new__(DiscoveryAgent)
        
        context = {"member_id": "12345"}
        
        # Direct value
        assert agent._resolve_input_value("direct", context) == "direct"
        
        # Context reference
        assert agent._resolve_input_value("${member_id}", context) == "12345"
        
        # Missing context key
        assert agent._resolve_input_value("${missing}", context) == "${missing}"
