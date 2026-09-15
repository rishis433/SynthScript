"""Unit tests for SynthScript schema models."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from synthscript.schema.models import (
    ArtifactMetadata,
    Contract,
    Locator,
    LocatorStrategy,
    ParameterDefinition,
    Target,
    ResolutionStrategy,
    StepAction,
    ActionType,
    BusinessException,
    SynthScriptArtifact,
)


class TestArtifactMetadata:
    """Tests for ArtifactMetadata model."""

    def test_valid_metadata(self):
        """Test creating valid ArtifactMetadata."""
        metadata = ArtifactMetadata(
            name="test_flow",
            version="1.0.0",
            target_surface="web",
        )
        assert metadata.name == "test_flow"
        assert metadata.version == "1.0.0"
        assert metadata.target_surface == "web"
        assert isinstance(metadata.created_at, datetime)

    def test_metadata_missing_required_field(self):
        """Test that validation fails when required fields are missing."""
        with pytest.raises(ValidationError) as exc_info:
            ArtifactMetadata(name="test_flow", version="1.0.0")
        assert "target_surface" in str(exc_info.value)

    def test_metadata_serialization(self):
        """Test serialization to JSON."""
        metadata = ArtifactMetadata(
            name="test_flow",
            version="1.0.0",
            target_surface="web",
        )
        json_str = metadata.model_dump_json()
        data = json.loads(json_str)
        assert data["name"] == "test_flow"
        assert data["version"] == "1.0.0"
        assert data["target_surface"] == "web"
        assert "created_at" in data

    def test_metadata_deserialization(self):
        """Test deserialization from JSON."""
        json_data = {
            "name": "test_flow",
            "version": "1.0.0",
            "target_surface": "web",
            "created_at": "2026-09-09T12:00:00",
        }
        metadata = ArtifactMetadata(**json_data)
        assert metadata.name == "test_flow"
        assert metadata.version == "1.0.0"
        assert metadata.target_surface == "web"


class TestParameterDefinition:
    """Tests for ParameterDefinition model."""

    def test_valid_parameter(self):
        """Test creating valid ParameterDefinition."""
        param = ParameterDefinition(type="string", required=True, pii=False)
        assert param.type == "string"
        assert param.required is True
        assert param.pii is False

    def test_parameter_defaults(self):
        """Test default values for ParameterDefinition."""
        param = ParameterDefinition(type="string")
        assert param.required is True
        assert param.pii is False

    def test_parameter_missing_type(self):
        """Test that validation fails when type is missing."""
        with pytest.raises(ValidationError) as exc_info:
            ParameterDefinition(required=True)
        assert "type" in str(exc_info.value)


class TestContract:
    """Tests for Contract model."""

    def test_valid_contract(self):
        """Test creating valid Contract."""
        contract = Contract(
            input_parameters={
                "username": ParameterDefinition(type="string", required=True),
                "password": ParameterDefinition(type="string", required=True, pii=True),
            },
            output_parameters={
                "token": ParameterDefinition(type="string", required=False),
            },
        )
        assert len(contract.input_parameters) == 2
        assert len(contract.output_parameters) == 1
        assert contract.input_parameters["password"].pii is True

    def test_empty_contract(self):
        """Test creating empty Contract."""
        contract = Contract()
        assert len(contract.input_parameters) == 0
        assert len(contract.output_parameters) == 0

    def test_contract_serialization(self):
        """Test serialization to JSON."""
        contract = Contract(
            input_parameters={"username": ParameterDefinition(type="string")},
        )
        json_str = contract.model_dump_json()
        data = json.loads(json_str)
        assert "input_parameters" in data
        assert "username" in data["input_parameters"]


class TestLocator:
    """Tests for Locator model."""

    def test_valid_locator(self):
        """Test creating valid Locator."""
        locator = Locator(
            strategy=LocatorStrategy.A11Y_ID,
            value="submit_button",
            confidence_threshold=0.9,
        )
        assert locator.strategy == LocatorStrategy.A11Y_ID
        assert locator.value == "submit_button"
        assert locator.confidence_threshold == 0.9

    def test_locator_defaults(self):
        """Test default values for Locator."""
        locator = Locator(strategy=LocatorStrategy.XPATH, value="//button[@type='submit']")
        assert locator.confidence_threshold == 0.8

    def test_locator_missing_strategy(self):
        """Test that validation fails when strategy is missing."""
        with pytest.raises(ValidationError) as exc_info:
            Locator(value="test")
        assert "strategy" in str(exc_info.value)

    def test_locator_missing_value(self):
        """Test that validation fails when value is missing."""
        with pytest.raises(ValidationError) as exc_info:
            Locator(strategy=LocatorStrategy.A11Y_ID)
        assert "value" in str(exc_info.value)

    def test_locator_invalid_confidence(self):
        """Test that validation fails for invalid confidence threshold."""
        with pytest.raises(ValidationError) as exc_info:
            Locator(strategy=LocatorStrategy.A11Y_ID, value="test", confidence_threshold=1.5)
        assert "confidence_threshold" in str(exc_info.value)


class TestTarget:
    """Tests for Target model."""

    def test_valid_target(self):
        """Test creating valid Target."""
        target = Target(
            locators=[
                Locator(strategy=LocatorStrategy.A11Y_ID, value="submit_button"),
                Locator(strategy=LocatorStrategy.XPATH, value="//button[@type='submit']"),
            ],
            resolution_strategy=ResolutionStrategy.CASCADE,
        )
        assert len(target.locators) == 2
        assert target.resolution_strategy == ResolutionStrategy.CASCADE

    def test_target_missing_locators(self):
        """Test that validation fails when locators is empty."""
        with pytest.raises(ValidationError) as exc_info:
            Target(locators=[], resolution_strategy=ResolutionStrategy.CASCADE)
        assert "locators" in str(exc_info.value)

    def test_target_default_resolution(self):
        """Test default resolution strategy."""
        target = Target(
            locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="test")]
        )
        assert target.resolution_strategy == ResolutionStrategy.CASCADE


class TestStepAction:
    """Tests for StepAction model."""

    def test_valid_step_with_target(self):
        """Test creating valid StepAction with target."""
        step = StepAction(
            step_id="step_1",
            action_type=ActionType.CLICK,
            target=Target(
                locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="submit")]
            ),
        )
        assert step.step_id == "step_1"
        assert step.action_type == ActionType.CLICK
        assert step.target is not None

    def test_valid_step_without_target(self):
        """Test creating valid StepAction without target (e.g., WAIT)."""
        step = StepAction(
            step_id="step_2",
            action_type=ActionType.WAIT,
        )
        assert step.step_id == "step_2"
        assert step.action_type == ActionType.WAIT
        assert step.target is None

    def test_step_with_bindings(self):
        """Test StepAction with input/output bindings."""
        step = StepAction(
            step_id="step_3",
            action_type=ActionType.TYPE_AND_ENTER,
            input_binding="username",
            output_binding="result",
            validation_rule="length > 0",
        )
        assert step.input_binding == "username"
        assert step.output_binding == "result"
        assert step.validation_rule == "length > 0"

    def test_step_missing_step_id(self):
        """Test that validation fails when step_id is missing."""
        with pytest.raises(ValidationError) as exc_info:
            StepAction(action_type=ActionType.CLICK)
        assert "step_id" in str(exc_info.value)

    def test_step_missing_action_type(self):
        """Test that validation fails when action_type is missing."""
        with pytest.raises(ValidationError) as exc_info:
            StepAction(step_id="step_1")
        assert "action_type" in str(exc_info.value)


class TestBusinessException:
    """Tests for BusinessException model."""

    def test_valid_exception(self):
        """Test creating valid BusinessException."""
        exception = BusinessException(
            condition="error_code == 404",
            return_state="NOT_FOUND",
        )
        assert exception.condition == "error_code == 404"
        assert exception.return_state == "NOT_FOUND"

    def test_exception_missing_condition(self):
        """Test that validation fails when condition is missing."""
        with pytest.raises(ValidationError) as exc_info:
            BusinessException(return_state="ERROR")
        assert "condition" in str(exc_info.value)

    def test_exception_missing_return_state(self):
        """Test that validation fails when return_state is missing."""
        with pytest.raises(ValidationError) as exc_info:
            BusinessException(condition="error")
        assert "return_state" in str(exc_info.value)


class TestSynthScriptArtifact:
    """Tests for SynthScriptArtifact model."""

    def test_valid_artifact(self):
        """Test creating valid SynthScriptArtifact."""
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(
                name="login_flow",
                version="1.0.0",
                target_surface="web",
            ),
            contract=Contract(
                input_parameters={
                    "username": ParameterDefinition(type="string"),
                    "password": ParameterDefinition(type="string", pii=True),
                },
                output_parameters={"token": ParameterDefinition(type="string")},
            ),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.TYPE_AND_ENTER,
                    target=Target(
                        locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="username")]
                    ),
                    input_binding="username",
                ),
                StepAction(
                    step_id="step_2",
                    action_type=ActionType.CLICK,
                    target=Target(
                        locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="submit")]
                    ),
                ),
            ],
            business_exceptions=[
                BusinessException(condition="error", return_state="FAILED")
            ],
        )
        assert artifact.metadata.name == "login_flow"
        assert len(artifact.flow) == 2
        assert len(artifact.business_exceptions) == 1

    def test_artifact_missing_metadata(self):
        """Test that validation fails when metadata is missing."""
        with pytest.raises(ValidationError) as exc_info:
            SynthScriptArtifact(
                contract=Contract(),
                flow=[StepAction(step_id="step_1", action_type=ActionType.WAIT)],
            )
        assert "metadata" in str(exc_info.value)

    def test_artifact_missing_contract(self):
        """Test that validation fails when contract is missing."""
        with pytest.raises(ValidationError) as exc_info:
            SynthScriptArtifact(
                metadata=ArtifactMetadata(name="test", version="1.0", target_surface="web"),
                flow=[StepAction(step_id="step_1", action_type=ActionType.WAIT)],
            )
        assert "contract" in str(exc_info.value)

    def test_artifact_empty_flow(self):
        """Test that validation fails when flow is empty."""
        with pytest.raises(ValidationError) as exc_info:
            SynthScriptArtifact(
                metadata=ArtifactMetadata(name="test", version="1.0", target_surface="web"),
                contract=Contract(),
                flow=[],
            )
        assert "flow" in str(exc_info.value)

    def test_artifact_serialization(self):
        """Test full artifact serialization to JSON."""
        artifact = SynthScriptArtifact(
            metadata=ArtifactMetadata(name="test", version="1.0", target_surface="web"),
            contract=Contract(),
            flow=[StepAction(step_id="step_1", action_type=ActionType.WAIT)],
        )
        json_str = artifact.model_dump_json()
        data = json.loads(json_str)
        assert "metadata" in data
        assert "contract" in data
        assert "flow" in data
        assert "business_exceptions" in data

    def test_artifact_deserialization(self):
        """Test full artifact deserialization from JSON."""
        json_data = {
            "metadata": {
                "name": "test",
                "version": "1.0",
                "target_surface": "web",
                "created_at": "2026-09-09T12:00:00",
            },
            "contract": {"input_parameters": {}, "output_parameters": {}},
            "flow": [
                {
                    "step_id": "step_1",
                    "action_type": "WAIT",
                    "target": None,
                    "input_binding": None,
                    "output_binding": None,
                    "validation_rule": None,
                }
            ],
            "business_exceptions": [],
        }
        artifact = SynthScriptArtifact(**json_data)
        assert artifact.metadata.name == "test"
        assert len(artifact.flow) == 1
        assert artifact.flow[0].action_type == ActionType.WAIT

    def test_artifact_round_trip(self):
        """Test serialization and deserialization round trip."""
        original = SynthScriptArtifact(
            metadata=ArtifactMetadata(name="test", version="1.0", target_surface="web"),
            contract=Contract(
                input_parameters={"username": ParameterDefinition(type="string")}
            ),
            flow=[
                StepAction(
                    step_id="step_1",
                    action_type=ActionType.CLICK,
                    target=Target(
                        locators=[Locator(strategy=LocatorStrategy.A11Y_ID, value="button")]
                    ),
                )
            ],
            business_exceptions=[
                BusinessException(condition="error", return_state="FAILED")
            ],
        )
        json_str = original.model_dump_json()
        restored = SynthScriptArtifact.model_validate_json(json_str)
        assert restored.metadata.name == original.metadata.name
        assert len(restored.flow) == len(original.flow)
        assert len(restored.business_exceptions) == len(original.business_exceptions)
