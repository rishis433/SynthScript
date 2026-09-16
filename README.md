## 1. Architecture

### Key Decisions & Trade-offs
SynthScript is built as a single-process Python CLI application. Python (3.11+) was chosen because it sits at the intersection of robust AI SDKs, automation frameworks (Playwright), and computer vision tooling (OpenCV, PyTesseract). A distributed, queue-based microservice architecture was deliberately avoided; while suitable for production scale, it introduces premature complexity for validating the core Observe-Decide-Act loop.

### LLM & Agent Loop
The system uses `gpt-4o` (via OpenAI Structured Outputs) strictly for the Discovery Phase. GPT-4o provides superior spatial and visual reasoning required for hostile UIs. The agent loop is fed a unified `SpatialSemanticTree`—a fusion of the Accessibility (A11y) tree and OCR bounding boxes—alongside a redacted screenshot. This ensures the LLM does not rely on HTML DOM, which is unreliable in legacy banking systems.

### Computer-Use Technology & Target Application
We utilize Playwright combined with PyTesseract (OCR). Playwright provides the browser execution and A11y snapshots, while OCR bridges the gap for non-semantic elements. 

For the target application, we built a local, intentionally hostile mock web app (Flask). It features iframes, nested tables, and no test IDs. This is preferable to a public site because it allows us to safely test PII redaction without exposing real data, avoid rate limits, and deterministically inject runtime failures (e.g., a "Record not found" state) to evaluate the system's error handling.

---

## 2. Artifact Schema

The Artifact is a strongly typed, versioned JSON file containing three main sections: `contract`, `flow`, and `business_exceptions`.
 
* **Contract:** Defines typed input parameters (e.g., `member_id`) and expected outputs (e.g., `balance`). This makes the artifact an invocable, reusable capability for upstream AI orchestrators.
* **Flow:** An ordered array of `StepAction` objects. Instead of raw LLM reasoning, each step contains a pure action (e.g., `TYPE_AND_ENTER`), input/output bindings, and a Target block holding cascading locators.
* **Business Exceptions:** Maps expected UI states (e.g., "Account Locked" text) to structured return codes.

This shape was chosen to completely decouple the probabilistic LLM discovery from the deterministic production runtime. The LLM produces the artifact once; the Replay Engine consumes it indefinitely.

---

## 3. Determinism & Error Handling

### Achieving Determinism
Determinism is achieved by strictly removing the LLM from the replay execution path. The Replay Engine is a standard state machine. To handle minor UI drift (e.g., a changed button ID), the engine uses a **Cascading Locator Strategy**. For each target, it attempts to resolve via:
1. **Accessibility ID** (fastest/most stable)
2. **OCR-relative positioning** (*e.g., "click the box right of 'Member ID'"*)
3. **Visual template matching** (pixel cropping)

### Error Taxonomy & Runtime Handling
The engine categorizes UI interruptions into three buckets:

* **Expected Business Outcomes:** If the OCR reads "No records found", the engine checks the `business_exceptions` block. It gracefully returns `{ status: "BUSINESS_OUTCOME", code: "NOT_FOUND" }`. This is a successful execution of the system, not a crash.
* **Recoverable Conditions:** Global interceptors handle known generic states, such as dismissing a "Session Expiring" modal, and automatically retry the current step.
* **Hard Failures:** If all locators exhaust and no business exception is met, the engine halts, captures a DOM snapshot and screenshot, and returns a strict failure payload for developer debugging.

---

## 4. Heterogeneity & Scale

### Surface Abstraction
To extend beyond web apps to legacy thick-clients or Citrix desktops, the architecture relies on the `SurfaceAdapter` base class. The JSON Artifact dictates *what* needs to be done, while the adapter dictates *how*. The Playwright web adapter can be swapped for an OS-level adapter (like PyAutoGUI or WinAppDriver) without changing a single line of the Replay Engine's core logic. Both adapters are required to output the same unified `SpatialSemanticTree` format.

### Multi-Tenant Reuse
Hundreds of institutions often run the same vendor software with minor configuration tweaks. Recording 500 distinct artifacts for 500 tenants is unsustainable. SynthScript addresses this via a **Layered Artifact Strategy**. 

A "Base Artifact" is recorded on the vanilla vendor app. For a specific tenant with a modified UI, the system generates a "Delta Patch" (e.g., *"Insert step 4a: fill out custom institution code"*). At runtime, the engine compiles the Base + Delta. If a tenant's UI drifts and breaks the flow, a local discovery run patches their specific Delta without affecting the other 499 tenants using the Base Artifact.

---

## 5. Escalation & Handoff

When the Replay Engine encounters a Hard Failure or is asked to execute a risky action without authorization, it initiates the **Human-in-the-Loop (HITL)** handoff.

* **Detect & Route:** The engine halts execution but explicitly keeps the Playwright browser context alive and frozen. It emits a `REQUIRES_INTERVENTION` event with the current screenshot and step context.
* **Take Control:** The human operator opens the live session (simulated via a mock terminal pause/local UI). They interact directly with the frozen DOM to resolve the blocker (e.g., solving a 2FA prompt). A background daemon logs these manual interventions.
* **Hand Back:** The operator clicks "Resume". The Replay Engine captures a fresh state of the screen, dynamically re-orients itself to the new UI, and seamlessly continues the remaining steps in the Artifact.

---

## 6. Safety

### Guardrail Model
Because this system operates on regulated financial data, the system utilizes a strict RBAC-style policy engine.

* **Allowlist:** The system is restricted to a configured list of permitted domains and internal IP routes.
* **Irreversible Actions:** Elements mapped to destructive roles (e.g., "Submit Transfer") require explicit injection of an `allow_destructive=True` flag from the caller. Without it, the engine treats the step as a Hard Failure and escalates to a human.
* **Data Redaction:** A local regex/NER proxy redacts sensitive fields (SSNs, Account Numbers) from the A11y tree and draws black bounding boxes over the raw screenshot before the payload is sent to the OpenAI API during the Discovery phase.

### Limits
The primary limitation is that local regex/NER redaction is imperfect. Highly obfuscated text, unusual formatting, or text embedded within complex graphics might bypass the OCR redactor and leak PII to the LLM during discovery.

---

## 7. Cuts

### What was left out:
1. A fully functional WebRTC operator console for remote live-session handoff.
2. Distributed database and Kafka message queues for multi-tenant routing.
3. A desktop application adapter (WinAppDriver).

**Why:** These features represent scaling infrastructure and broad feature sets. As per the constraints, the focus was kept strictly on the load-bearing pieces: the artifact schema, the deterministic execution loop, and the error taxonomy.

### What I'd build next:
With more time, I would build an **Agent-facing Capability Registry**—a lightweight API endpoint that exposes the saved JSON Artifacts as standard OpenAI Tool-Calling schemas. This would allow an upstream conversational agent to dynamically discover and invoke legacy capabilities (e.g., `execute_legacy_transfer(amount, to_account)`) as if they were modern APIs. 

I would also implement multi-run stability scoring to calculate a "flakiness" metric for newly generated artifacts before they are approved for unattended production execution.

---

## Quick Start & Setup

### Prerequisites
* Python 3.11+
* Node.js (for Playwright dependencies, if applicable)

### Installation
Set up the repository by downloading the packages.

1. **Clone the repository:**
   ```bash
   git clone https://github.com
   cd synthscript
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies and browser binaries:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

### Testing
To execute the test suite, run PyTest with the `-v` flag if necessary for verbose output.

```bash
python -m pytest -v
```

If you want to run commands continuously, use the `looponfail` flag (`-f`) which utilizes the `pytest-xdist` plugin to repeatedly run your tests in a subprocess. It will monitor your directory and automatically re-run previously failing tests whenever a file changes.

```bash
pip install pytest-xdist
python -m pytest -f
```
