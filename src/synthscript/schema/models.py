"""Pydantic v2 data models for SynthScript Artifact Schema."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class LocatorStrategy(str, Enum):
    """Strategy for locating UI elements."""

    A11Y_ID = "a11y_id"
    OCR_RELATIVE = "ocr_relative"
    CV_TEMPLATE = "cv_template"
    XPATH = "xpath"


class ResolutionStrategy(str, Enum):
    """Strategy for resolving multiple locators."""

    CASCADE = "cascade"
    FIRST_MATCH = "first_match"


class ActionType(str, Enum):
    """Types of actions that can be performed in a step."""

    CLICK = "CLICK"
    TYPE_AND_ENTER = "TYPE_AND_ENTER"
    EXTRACT_TEXT = "EXTRACT_TEXT"
    WAIT = "WAIT"


class ArtifactMetadata(BaseModel):
    """Metadata about the SynthScript artifact."""

    name: str = Field(..., description="Name of the automation flow")
    version: str = Field(..., description="Version of the artifact")
    target_surface: str = Field(..., description="Target application/surface")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the artifact was created",
    )


class ParameterDefinition(BaseModel):
    """Definition of a parameter (input or output)."""

    type: str = Field(..., description="Type of the parameter")
    required: bool = Field(default=True, description="Whether the parameter is required")
    pii: bool = Field(default=False, description="Whether the parameter contains PII data")


class Contract(BaseModel):
    """Contract defining input and output parameters for the automation."""

    input_parameters: dict[str, ParameterDefinition] = Field(
        default_factory=dict,
        description="Input parameters for the automation",
    )
    output_parameters: dict[str, ParameterDefinition] = Field(
        default_factory=dict,
        description="Output parameters from the automation",
    )


class Locator(BaseModel):
    """Locator strategy for finding UI elements."""

    strategy: LocatorStrategy = Field(..., description="Strategy for locating the element")
    value: str = Field(..., description="Locator value")
    confidence_threshold: Optional[float] = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for match",
    )


class Target(BaseModel):
    """Target definition with multiple locators and resolution strategy."""

    locators: list[Locator] = Field(
        ...,
        min_length=1,
        description="List of locators to find the element",
    )
    resolution_strategy: ResolutionStrategy = Field(
        default=ResolutionStrategy.CASCADE,
        description="Strategy for resolving multiple locators",
    )


class StepAction(BaseModel):
    """A single step in the automation flow."""

    step_id: str = Field(..., description="Unique identifier for this step")
    action_type: ActionType = Field(..., description="Type of action to perform")
    target: Optional[Target] = Field(default=None, description="Target element for the action")
    input_binding: Optional[str] = Field(
        default=None,
        description="Binding to input parameter for this step",
    )
    output_binding: Optional[str] = Field(
        default=None,
        description="Binding to output parameter for this step",
    )
    validation_rule: Optional[str] = Field(
        default=None,
        description="Validation rule to apply after the action",
    )


class BusinessException(BaseModel):
    """Business exception handling definition."""

    condition: str = Field(..., description="Condition that triggers this exception")
    return_state: str = Field(..., description="State to return when exception occurs")


class SynthScriptArtifact(BaseModel):
    """Root artifact containing the complete automation definition."""

    metadata: ArtifactMetadata = Field(..., description="Artifact metadata")
    contract: Contract = Field(..., description="Input/output contract")
    flow: list[StepAction] = Field(..., min_length=1, description="Sequence of automation steps")
    business_exceptions: list[BusinessException] = Field(
        default_factory=list,
        description="Business exception handlers",
    )
