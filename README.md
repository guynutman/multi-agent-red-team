# multi-agent-red-team

A multi-agent LLM red-teaming system that probes a target model for prompt injection vulnerabilities. Built from scratch (no agent frameworks) as a learning project and portfolio artifact.

## Overview

An orchestrator dispatches specialized sub-agents to attempt prompt injection attacks against a target LLM. Each attempt is judged for success and logged. At the end of a campaign, a structured Markdown report summarizes findings.

**v1 scope:** two sub-agents (Basic Injection, External Prompt Injection) attacking Llama 3 8B locally via Ollama, using Gemini Flash as the attacker.

## Architecture

```
User CLI → Orchestrator → dispatches → Sub-agents (attack strategies)
                             ↓                     ↓
                          Storage           LLM Interface
                          (SQLite)          (call_llm — pluggable)
                                                    ↓
                                            Target Model (Llama 3 via Ollama)
                             ↓
                          Report Generator → structured Markdown report
```

### Components

1. **LLM Interface** — pluggable `call_llm(messages, backend, **config)` supporting Ollama and Gemini for v1. Uniform OpenAI-style messages format across backends.
2. **Orchestrator** — controls the campaign: dispatches sub-agents, manages budget, aggregates results.
3. **Sub-agents** — specialized attackers. Each implements one attack category and generates payloads via the attacker LLM.
4. **Judge / Success Evaluator** — LLM-based evaluator that decides whether an injection succeeded, given the attempt's success criterion.
5. **Storage** — SQLite database for campaigns, attempts, and judgments.
6. **Report Generator** — reads storage, produces final Markdown report.

## End-to-End Workflow

A single campaign run, top to bottom:

1. **User invokes CLI** with campaign name, target model, attacker model, sub-agents, and budget. `main.py` parses these into a config.
2. **Orchestrator constructs backends** — one `LLMBackend` for the attacker (Gemini), one for the target (Ollama). Concrete classes chosen once here; everything downstream stays provider-agnostic via the `LLMBackend` Protocol.
3. **Orchestrator opens Storage** — SQLite file created if missing. Inserts a new campaign row and receives a `campaign_id`.
4. **Orchestrator enters the main loop** (up to `budget` iterations):
   1. Picks the next sub-agent (round-robin).
   2. **Sub-agent generates a payload** by calling the attacker LLM through `call_llm(messages, attacker_backend)`. Returns a JSON object with `payload`, optional `context` (for indirect injection), and `success_criterion`.
   3. **Sub-agent sends the attack to the target** by calling `call_llm([{role: "user", content: <context + payload>}], target_backend)`. Records `retries` from the response.
   4. **Storage.record_attempt** persists payload, context, target response, and retry count. Returns `attempt_id`.
   5. **Judge evaluates** the attempt by calling the attacker LLM again with the success criterion and the target's response. Returns a verdict (`success` | `failure` | `unclear`) and reasoning.
   6. **Storage.record_judgment** persists the judgment linked to the attempt.
   7. **Orchestrator logs**, decrements budget, loops.
5. **Orchestrator marks the campaign finished** via `Storage.finish_campaign(campaign_id, "completed")`.
6. **Report Generator reads all attempts + judgments** for the campaign via `get_campaign_attempts(campaign_id)` and writes a Markdown report.

Every arrow above is a function call. No component talks directly to another provider's API — everything routes through `call_llm(messages, backend)`, so switching providers is a one-line change in `main.py`.

## Tech Stack

- Python 3.10+
- `httpx` — HTTP client for LLM API calls
- `pydantic` — structured output validation
- `sqlite3` — storage (stdlib)
- `pytest` — testing
- `python-dotenv` — env-var loading for API keys
- Ollama — local target model runtime
- Gemini API — attacker + judge

## Sub-agents (v1)

- **Basic Injection** — direct instruction override sent to the target. No wrapping context.
- **External Prompt Injection** — indirect injection via a wrapping document / webpage / tool output containing the payload.

**Deferred to v2:** Context Switch, Translation Injection.

## Models

- **Target:** Llama 3 8B via Ollama (local, free, fast iteration)
- **Attacker:** Gemini Flash (via `gemini-flash-latest`) via free API tier
- **Judge:** Gemini Flash (same as attacker; separated logically, not by model)

## Data Model

### Entities

- **Campaign** — one CLI invocation. Metadata about the run.
- **Attempt** — one injection try by a sub-agent against the target.
- **Judgment** — the evaluator's verdict on an attempt.

### Relationships

```
Campaign 1──* Attempt 1──1 Judgment
                │
                └─ tagged with sub_agent_type
```

One campaign has many attempts; each attempt has exactly one judgment. Findings are a query over successful attempts, not a separate table.

### SQLite schema

```sql
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_model TEXT NOT NULL,
    attacker_model TEXT NOT NULL,
    budget INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    sub_agent_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    target_context TEXT,
    target_response TEXT NOT NULL,
    retries INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id),
    verdict TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    judged_at TEXT NOT NULL
);
```

## Setup

### Prerequisites

- Python 3.10+
- [uv](https://astral.sh/uv) for dependency management
- [Ollama](https://ollama.com/download) for the local target model
- A Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Install

```bash
git clone https://github.com/<your-username>/multi-agent-red-team.git
cd multi-agent-red-team
uv sync
```

Create a `.env` file:
```
GEMINI_API_KEY=<your-key-here>
```

Pull the target model and start Ollama:
```bash
ollama pull llama3:8b
ollama serve &
```

### Run tests

```bash
uv run python -m tests.test_backends
uv run python -m tests.test_storage
```

## Usage

```bash
uv run python main.py \
  --campaign-name "basic_vs_llama3_round1" \
  --target ollama:llama3:8b \
  --attacker gemini:gemini-flash-latest \
  --sub-agents basic,external \
  --budget 20 \
  --output-report reports/basic_vs_llama3_round1.md
```

## Report Format

Markdown, generated post-campaign:

- **Metadata** — models, dates, totals, success rates by sub-agent
- **Summary** — success count / breakdown by category
- **Successful Findings** — for each success: payload, target response (truncated), judge reasoning
- **Failed Attempts (sampled)** — 5–10 illustrative failures with reasoning
- **Method Notes** — architecture, limitations, target model version

## Design Decisions

- **Multi-agent architecture** over single agent — specialization = better attacks per agent, parallelizable, independently tunable.
- **From scratch, no agent frameworks** — target audience is AI safety hiring, which cares about primitive understanding (orchestration loops, tool-calling protocol, state management, retries) more than framework fluency.
- **2 sub-agents for v1** — shipping 2 well beats shipping 4 half-built. Basic + External span the direct/indirect fundamental variants.
- **Llama 3 8B as target** — free, local, weak enough safety training to yield findings worth reporting.
- **Gemini Flash as attacker** — stronger payload generation than Llama 3; free tier is sufficient for a 2-week project.
- **Pluggable LLM interface** — swap backends by changing one module. Standard professional pattern.
- **OpenAI-style messages format** — de facto industry standard; minor per-provider transforms handled inside each backend.
- **SQLite for storage** — zero config, single file, stdlib support.
- **JSON as structured output format** — universal, pydantic-validatable, catches parsing errors cleanly.
- **Local-only deployment (no Docker, no cloud)** — v1 is about the red-teaming system, not infra.
- **Per-attempt success criterion (generated by attacker)** — different injections have different definitions of "worked"; a universal check fails for creative attacks.
- **Attempt/Judgment separation** — allows re-judging with a better evaluator later without re-running the target.

## Limitations (v1)

- Tested only against Llama 3 8B; findings may not transfer to frontier models with stronger safety training.
- Attacker LLM (Gemini) shares biases with the target's language model class; certain attack surfaces are systematically missed.
- Heuristic orchestration (round-robin) doesn't learn from failures over time.
- No true novelty detection — rediscovers known attacks rather than finding new categories.
- Target is bare Llama 3, not an agentic system with tools; downstream attack categories (SSRF, SQLi, RCE, XSS, IDOR from OWASP LLM Top 10) are out of scope.

## Roadmap

**v2:** Add Context Switch and Translation Injection sub-agents. Add a second target for cross-model comparison. Add a learned dispatch policy (bandit or RL) to replace heuristic orchestration.

**v3:** Extend to agentic-system attacks — target model wrapped with tools/DB/network access — enabling probes for downstream OWASP categories.

## References

- Simon Willison — prompt injection blog posts (simonwillison.net)
- OWASP Top 10 for LLM Applications — LLM01: Prompt Injection
- Perez & Ribeiro — *Ignore Previous Prompt: Attack Techniques For Language Models* (2022)
- Joseph Thacker — *Prompt Injection Primer for Engineers* (PIPE, 2023)
- Debenedetti et al. — *Defeating Prompt Injections by Design* (CaMeL, Google DeepMind, 2025)

## License

MIT