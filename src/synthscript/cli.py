"""CLI for SynthScript discovery and replay."""

import asyncio
import json
from pathlib import Path
from typing import Optional

import click

from synthscript.discovery.agent import DiscoveryAgent
from synthscript.discovery.compiler import ArtifactCompiler
from synthscript.runtime.replay import ReplayEngine
from synthscript.adapters.playwright_adapter import PlaywrightWebAdapter
from synthscript.schema.models import SynthScriptArtifact


@click.group()
def cli():
    """SynthScript CLI for UI automation discovery and replay."""
    pass


@cli.command()
@click.option(
    "--goal",
    required=True,
    help="The goal to achieve (e.g., 'Search for member 12345')",
)
@click.option(
    "--url",
    required=True,
    help="URL of the target application",
)
@click.option(
    "--output",
    default="evidence/artifact.json",
    help="Output path for the generated artifact",
)
@click.option(
    "--headless/--no-headless",
    default=True,
    help="Run browser in headless mode",
)
@click.option(
    "--model",
    default="gpt-4",
    help="LLM model to use for discovery",
)
@click.option(
    "--max-steps",
    default=20,
    help="Maximum number of discovery steps",
)
@click.option(
    "--api-key",
    envvar="OPENAI_API_KEY",
    help="OpenAI API key (or set OPENAI_API_KEY env var)",
)
def discover(
    goal: str,
    url: str,
    output: str,
    headless: bool,
    model: str,
    max_steps: int,
    api_key: Optional[str],
):
    """Run LLM-driven discovery to generate a SynthScript artifact."""
    async def run_discovery():
        # Ensure evidence directory exists
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        click.echo(f"Starting discovery for goal: {goal}")
        click.echo(f"Target URL: {url}")
        click.echo(f"Using model: {model}")
        
        # Initialize adapter
        adapter = PlaywrightWebAdapter(headless=headless)
        await adapter.start(url)
        
        try:
            # Initialize discovery agent
            agent = DiscoveryAgent(
                llm_provider="openai",
                model=model,
                max_steps=max_steps,
                api_key=api_key,
            )
            
            # Run discovery
            click.echo("Running discovery...")
            result = await agent.discover(goal, adapter)
            
            if result.success:
                click.echo("✓ Discovery successful!")
                
                # Compile artifact
                compiler = ArtifactCompiler()
                artifact = compiler.compile(
                    discovery_result=result,
                    artifact_name="discovered_flow",
                    artifact_version="1.0.0",
                    target_surface="web",
                )
                
                # Save artifact
                compiler.save_artifact(artifact, output)
                click.echo(f"✓ Artifact saved to: {output}")
                
                # Save discovery log
                log_path = output_path.parent / "discovery_log.json"
                with open(log_path, "w") as f:
                    json.dump(result.to_dict(), f, indent=2)
                click.echo(f"✓ Discovery log saved to: {log_path}")
                
            else:
                click.echo(f"✗ Discovery failed: {result.error_message}")
                
                # Save failed discovery log
                log_path = output_path.parent / "discovery_log_failed.json"
                with open(log_path, "w") as f:
                    json.dump(result.to_dict(), f, indent=2)
                click.echo(f"✓ Failed discovery log saved to: {log_path}")
                
        finally:
            await adapter.close()
    
    asyncio.run(run_discovery())


@cli.command()
@click.option(
    "--artifact",
    required=True,
    help="Path to the SynthScript artifact JSON file",
)
@click.option(
    "--url",
    required=True,
    help="URL of the target application",
)
@click.option(
    "--input",
    multiple=True,
    help="Input parameters (format: key=value)",
)
@click.option(
    "--output",
    default="evidence/replay_log.json",
    help="Output path for the replay log",
)
@click.option(
    "--headless/--no-headless",
    default=True,
    help="Run browser in headless mode",
)
@click.option(
    "--log-dir",
    default="evidence",
    help="Directory to save execution logs",
)
def replay(
    artifact: str,
    url: str,
    input: tuple,
    output: str,
    headless: bool,
    log_dir: str,
):
    """Replay a SynthScript artifact deterministically."""
    async def run_replay():
        # Ensure evidence directory exists
        log_path = Path(output)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Parse input parameters
        input_params = {}
        for param in input:
            if "=" in param:
                key, value = param.split("=", 1)
                input_params[key] = value
        
        click.echo(f"Loading artifact from: {artifact}")
        click.echo(f"Target URL: {url}")
        click.echo(f"Input parameters: {input_params}")
        
        # Load artifact
        compiler = ArtifactCompiler()
        synthscript_artifact = compiler.load_artifact(artifact)
        click.echo(f"✓ Loaded artifact: {synthscript_artifact.metadata.name}")
        
        # Initialize adapter
        adapter = PlaywrightWebAdapter(headless=headless)
        await adapter.start(url)
        
        try:
            # Initialize replay engine
            engine = ReplayEngine(log_dir=Path(log_dir))
            
            # Run replay
            click.echo("Running replay...")
            result = await engine.execute(
                artifact=synthscript_artifact,
                input_params=input_params,
                adapter=adapter,
            )
            
            # Save result
            with open(log_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2, default=str)
            
            click.echo(f"✓ Replay log saved to: {log_path}")
            
            if result.status.value == "SUCCESS":
                click.echo("✓ Replay successful!")
            elif result.status.value == "BUSINESS_OUTCOME":
                click.echo(f"⚠ Business outcome: {result.error.code if result.error else 'Unknown'}")
            elif result.status.value == "RECOVERABLE_ERROR":
                click.echo("⚠ Recoverable error occurred")
            else:
                click.echo(f"✗ Hard failure: {result.error.error_message if result.error else 'Unknown'}")
                
        finally:
            await adapter.close()
    
    asyncio.run(run_replay())


if __name__ == "__main__":
    cli()
