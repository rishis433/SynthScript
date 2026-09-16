# SynthScript

SynthScript is a Python framework for discovering and replaying computer-use
workflows against legacy user interfaces. An LLM is used during discovery to
turn a natural-language goal into a typed, versioned artifact. Replay then
executes that artifact deterministically without calling the LLM.

The repository includes a deliberately hostile local banking application with
nested tables and an iframe. It is safe to use for demonstrations and tests.

## Requirements

- Python 3.11 or newer
- Node.js is not required directly, but Playwright downloads and runs a
  Chromium browser
- An OpenAI API key is required only for LLM-driven discovery

## Installation

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/rishis433/SynthScript.git
cd SynthScript

python -m venv .venv
```

Activate the environment:

```bash
# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the package and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

If you want only install for replay:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
python -m playwright install chromium
```

## Configuration

Discovery uses the OpenAI API. Set the key in the environment before running
the `discover` command:

```bash
# macOS/Linux
export OPENAI_API_KEY="your-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY = "your-api-key"
```

Do not commit API keys to the repository. The `replay` command does not need an
API key because it consumes an existing artifact.

## Run the local demonstration app

Start the mock banking application from the repository root:

```bash
python -m flask --app tests.mock_app.app run --host 127.0.0.1 --port 5000
```

The application is available at <http://127.0.0.1:5000>. Leave this process
running while executing discovery or replay in a second terminal.

## End-to-end discovery and replay

With the mock application running and `OPENAI_API_KEY` configured, discover a
flow for a known member:

```bash
python -m synthscript.cli discover \
  --goal "Search for member 12345" \
  --url http://127.0.0.1:5000 \
  --output evidence/artifact.json \
  --model gpt-4o
```

This writes the compiled artifact to `evidence/artifact.json` and the discovery
trace to `evidence/discovery_log.json`.

Replay the generated artifact:

```bash
python -m synthscript.cli replay \
  --artifact evidence/artifact.json \
  --url http://127.0.0.1:5000 \
  --output evidence/replay_log.json \
  --log-dir evidence
```

To exercise the mock application's not-found path during discovery, use the
following goal:

```bash
python -m synthscript.cli discover \
  --goal "Search for member 999" \
  --url http://127.0.0.1:5000 \
  --output evidence/artifact_not_found.json \
  --model gpt-4o
```

The mock application intentionally returns a `Record not found` state for
member `999`, allowing the resulting discovery and replay logs to demonstrate
exception handling.

## Replay without live services

After installation, replay is fully local and does not call an LLM. The
repository includes a sample artifact and captured logs in `evidence/`.
Start the mock application, then run:

```bash
python -m synthscript.cli replay \
  --artifact evidence/artifact.json \
  --url http://127.0.0.1:5000 \
  --output evidence/replay_log_local.json \
  --log-dir evidence
```

This path requires only the local mock application and the Playwright browser.
No OpenAI key or external application is needed.

## Testing

Run the complete test suite:

```bash
python -m pytest -q
```

For verbose output
```bash
python -m pytest -v
```

The tests cover the schema, discovery components, locator and adapter behavior,
deterministic replay, business/error outcomes, HITL handoff, and security/PII
redaction.

## Design write-up

See [REPORT.md](REPORT.md) for the design write-up covering:

1. Architecture
2. Artifact schema
3. Determinism & error handling
4. Heterogeneity & multi-tenant
5. Escalation & handoff
6. Safety
7. Cuts
8. Multi-run stability
