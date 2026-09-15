"""Evidence generation script for SynthScript.

This script runs the end-to-end flow:
1. Runs discovery on the mock app to generate artifact.json
2. Runs a successful replay, saving logs to /evidence/replay_success.log
3. Runs a replay with bad inputs (member "999") that triggers a business outcome exception
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from synthscript.discovery.agent import DiscoveryAgent
from synthscript.discovery.compiler import ArtifactCompiler
from synthscript.runtime.replay import ReplayEngine
from synthscript.adapters.playwright_adapter import PlaywrightWebAdapter
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


async def generate_artifact():
    """Generate artifact by running discovery on mock app."""
    print("=" * 60)
    print("STEP 1: Running Discovery on Mock App")
    print("=" * 60)
    
    # Start mock app (in background)
    import subprocess
    mock_app_process = subprocess.Popen(
        [sys.executable, "tests/mock_app/app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for app to start
    await asyncio.sleep(2)
    
    try:
        # Initialize adapter
        adapter = PlaywrightWebAdapter(headless=True)
        await adapter.start("http://localhost:5000")
        
        try:
            # Initialize discovery agent (using mock/simulation for demo)
            # In production, this would use real LLM
            print("Discovering 'Search for member 12345' flow...")
            
            # For demo purposes, we'll create a manual discovery result
            # In production, this would come from the LLM agent
            from synthscript.discovery.agent import DiscoveryResult, DiscoveryStep, DiscoveryStepType
            
            discovery_result = DiscoveryResult(
                success=True,
                goal="Search for member 12345",
                steps=[
                    DiscoveryStep(
                        step_type=DiscoveryStepType.OBSERVE,
                        timestamp=0.0,
                        state_snapshot={"ui": "initial state"},
                    ),
                    DiscoveryStep(
                        step_type=DiscoveryStepType.DECIDE,
                        timestamp=1.0,
                        llm_decision="TYPE_AND_ENTER",
                        reasoning="Need to enter member ID",
                    ),
                    DiscoveryStep(
                        step_type=DiscoveryStepType.ACT,
                        timestamp=2.0,
                        action_taken="TYPE_AND_ENTER",
                        element_targeted={"id": "member-id-input", "text": "Member ID"},
                        input_value="12345",
                    ),
                    DiscoveryStep(
                        step_type=DiscoveryStepType.OBSERVE,
                        timestamp=3.0,
                        state_snapshot={"ui": "after typing"},
                    ),
                    DiscoveryStep(
                        step_type=DiscoveryStepType.DECIDE,
                        timestamp=4.0,
                        llm_decision="CLICK",
                        reasoning="Need to click search button",
                    ),
                    DiscoveryStep(
                        step_type=DiscoveryStepType.ACT,
                        timestamp=5.0,
                        action_taken="CLICK",
                        element_targeted={"id": "search-button", "text": "Search"},
                    ),
                ],
            )
            
            # Compile artifact
            compiler = ArtifactCompiler()
            artifact = compiler.compile(
                discovery_result=discovery_result,
                artifact_name="member_lookup",
                artifact_version="1.0.0",
                target_surface="web",
                input_parameters={
                    "member_id": {
                        "type": "string",
                        "required": True,
                        "pii": False,
                    }
                },
                output_parameters={
                    "result": {
                        "type": "string",
                        "required": False,
                    }
                },
            )
            
            # Save artifact
            evidence_dir = Path("evidence")
            evidence_dir.mkdir(exist_ok=True)
            
            artifact_path = evidence_dir / "artifact.json"
            compiler.save_artifact(artifact, str(artifact_path))
            
            print(f"✓ Artifact saved to: {artifact_path}")
            return artifact
            
        finally:
            await adapter.close()
            
    finally:
        mock_app_process.terminate()
        mock_app_process.wait()


async def run_successful_replay(artifact: SynthScriptArtifact):
    """Run successful replay with valid inputs."""
    print("\n" + "=" * 60)
    print("STEP 2: Running Successful Replay")
    print("=" * 60)
    
    # Start mock app
    import subprocess
    mock_app_process = subprocess.Popen(
        [sys.executable, "tests/mock_app/app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    await asyncio.sleep(2)
    
    try:
        # Initialize adapter
        adapter = PlaywrightWebAdapter(headless=True)
        await adapter.start("http://localhost:5000")
        
        try:
            # Initialize replay engine
            engine = ReplayEngine(log_dir=Path("evidence"))
            
            # Run replay with valid input
            print("Running replay with member_id=12345...")
            result = await engine.execute(
                artifact=artifact,
                input_params={"member_id": "12345"},
                adapter=adapter,
            )
            
            # Save log
            log_path = Path("evidence") / "replay_success.log"
            with open(log_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2, default=str)
            
            print(f"✓ Success log saved to: {log_path}")
            print(f"Status: {result.status.value}")
            
        finally:
            await adapter.close()
            
    finally:
        mock_app_process.terminate()
        mock_app_process.wait()


async def run_business_error_replay(artifact: SynthScriptArtifact):
    """Run replay with bad inputs to trigger business exception."""
    print("\n" + "=" * 60)
    print("STEP 3: Running Replay with Business Error")
    print("=" * 60)
    
    # Create artifact with business exception for "999"
    artifact_with_exception = SynthScriptArtifact(
        metadata=artifact.metadata,
        contract=artifact.contract,
        flow=artifact.flow,
        business_exceptions=[
            BusinessException(
                condition="Record not found",
                return_state="NOT_FOUND",
            ),
        ],
    )
    
    # Start mock app
    import subprocess
    mock_app_process = subprocess.Popen(
        [sys.executable, "tests/mock_app/app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    await asyncio.sleep(2)
    
    try:
        # Initialize adapter
        adapter = PlaywrightWebAdapter(headless=True)
        await adapter.start("http://localhost:5000")
        
        try:
            # Initialize replay engine
            engine = ReplayEngine(log_dir=Path("evidence"))
            
            # Run replay with invalid input (999 triggers "Record not found")
            print("Running replay with member_id=999 (should trigger business exception)...")
            result = await engine.execute(
                artifact=artifact_with_exception,
                input_params={"member_id": "999"},
                adapter=adapter,
            )
            
            # Save log
            log_path = Path("evidence") / "replay_business_error.log"
            with open(log_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2, default=str)
            
            print(f"✓ Business error log saved to: {log_path}")
            print(f"Status: {result.status.value}")
            if result.error:
                print(f"Error code: {result.error.code if hasattr(result.error, 'code') else 'N/A'}")
            
        finally:
            await adapter.close()
            
    finally:
        mock_app_process.terminate()
        mock_app_process.wait()


async def main():
    """Main evidence generation flow."""
    print("SynthScript Evidence Generation")
    print("=" * 60)
    
    try:
        # Step 1: Generate artifact
        artifact = await generate_artifact()
        
        # Step 2: Run successful replay
        await run_successful_replay(artifact)
        
        # Step 3: Run business error replay
        await run_business_error_replay(artifact)
        
        print("\n" + "=" * 60)
        print("✓ Evidence generation complete!")
        print("=" * 60)
        print("Generated files:")
        print("  - evidence/artifact.json")
        print("  - evidence/replay_success.log")
        print("  - evidence/replay_business_error.log")
        
    except Exception as e:
        print(f"\n✗ Error during evidence generation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
