# multi-agent-red-team

A multi-agent LLM red-teaming system that probes a target model for prompt-injection vulnerabilities. Built from scratch (no agent frameworks like LangChain or AutoGen) as a learning project and portfolio artifact.

## Overview

An **orchestrator** dispatches specialized **sub-agents** to attempt prompt-injection attacks against a target LLM. Each attempt is judged for success and logged to SQLite. At the end of a campaign, a structured Markdown report summarizes findings.

**v1 scope:** two sub-agents (direct injection, indirect injection via wrapping document) attacking Llama 3 8B locally via Ollama. Attacker and judge default to a local uncensored model (`dolphin-mistral`) for a fully-local free workflow; the pluggable LLM interface lets you swap either to Gemini or any other provider with a one-line change.

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

1. **LLM Interface (`llm/`)** — pluggable `call_llm(messages, backend, **config)` supporting Ollama and Gemini for v1. Every backend implements the same `LLMBackend` Protocol; adding a new provider means one new file, no changes elsewhere.
2. **Sub-agents (`subagents/`)** — specialized attackers. Each subclass of `SubAgent` implements one attack category and generates JSON payloads via the attacker LLM. v1 ships `BasicInjectionSubAgent` (direct) and `ExternalInjectionSubAgent` (indirect).
3. **Judge (`judge.py`)** — LLM-based evaluator. Reads the payload, target response, and the sub-agent's per-attempt success criterion, returns a structured verdict (`success` | `failure` | `unclear`) with reasoning.
4. **Orchestrator (`orchestrator.py`)** — controls the campaign: round-robin sub-agent dispatch, budget enforcement, per-attempt error isolation, campaign lifecycle.
5. **Storage (`storage/db.py`)** — SQLite persistence for campaigns, attempts, and judgments. Context-manager pattern for clean teardown.
6. **Report Generator (`report.py`)** — reads storage, writes a Markdown report with metadata, summary tables, and full attempt log. Also runs standalone against an existing DB.
7. **CLI (`main.py`)** — argparse entry point. String specs like `ollama:llama3:8b` are parsed into backends via a small registry.

## End-to-End Workflow

A single campaign run, top to bottom:

1. **User invokes CLI** with campaign name, target model, attacker model, sub-agents, and budget.
2. **`main.py` constructs backends** from string specs via `build_backend()` — one for the target, one for the attacker, one for the judge (defaults to attacker).
3. **Orchestrator opens Storage** — SQLite file created if missing. Inserts a new campaign row and receives a `campaign_id`.
4. **Orchestrator enters the main loop** (up to `budget` iterations):
    1. Picks the next sub-agent (round-robin: `subagents[attempt % len(subagents)]`).
    2. **Sub-agent generates a payload** by calling the attacker LLM through `call_llm(messages, attacker_backend, temperature=1.0)`. Returns a validated `InjectionSpec` (`payload`, optional `context`, `success_criterion`).
    3. **Orchestrator sends the attack to the target** by calling `call_llm(messages, target_backend, temperature=0.7)`. For basic direct injection, the payload is the user message; for external indirect injection, the payload is embedded inside a `context` document that the target is asked to summarize.
    4. **Storage.record_attempt** persists payload, context, target response, retry count.
    5. **Judge evaluates** the attempt with `call_llm(..., temperature=0.0)` for determinism. Returns a `Verdict`.
    6. **Storage.record_judgment** persists the verdict linked to the attempt.
    7. **Orchestrator logs one line** with attempt number, sub-agent type, and verdict.
    8. **Any exception in this loop body is caught** so one flaky attempt doesn't kill the run.
5. **Orchestrator marks the campaign finished** (`completed` or `aborted` on top-level failure).
6. **Report Generator** reads all attempts + judgments via `get_campaign_attempts(campaign_id)` and writes the Markdown report.

Every arrow above is a function call. No component talks directly to a provider's API — everything routes through `call_llm(messages, backend)`, so switching providers is a one-line change in `main.py`.

## Tech Stack

- Python 3.10+
- `httpx` — HTTP client for LLM API calls
- `pydantic` — structured output validation
- `sqlite3` — storage (stdlib)
- `python-dotenv` — env-var loading for optional API keys
- [uv](https://astral.sh/uv) — dependency management
- [Ollama](https://ollama.com/download) — local model runtime for both target and default attacker
- (optional) Gemini API — swap-in attacker/judge via the free tier

## Setup

### Prerequisites

- **Python 3.10+** and **[uv](https://astral.sh/uv)** installed
- **[Ollama](https://ollama.com/download)** installed and running locally
- **~10 GB free disk** for both models (`llama3:8b` ≈ 5 GB, `dolphin-mistral` ≈ 4 GB)
- **~12 GB RAM** if running both models loaded simultaneously; if less, run with a single Ollama model and reuse it for both attacker and target
- (optional) A **Gemini API key** from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) if you want to swap the attacker/judge to Gemini

### Install (Ubuntu / WSL)

```bash
# clone
git clone git@github.com:guynutman/multi-agent-red-team.git
cd multi-agent-red-team

# Python deps into a project-local venv
uv sync

# system dependency needed by the Ollama installer
sudo apt-get update && sudo apt-get install -y zstd curl

# Ollama
curl -fsSL https://ollama.com/install.sh | sh

# start Ollama in the background; keep models warm for 10 min after each call
export OLLAMA_KEEP_ALIVE=10m
ollama serve &

# pull the two default models
ollama pull llama3:8b
ollama pull dolphin-mistral

# (optional) Gemini key — only needed if you plan to use --attacker gemini:...
cp .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

### Verify

```bash
curl http://localhost:11434/api/tags     # Ollama alive, lists installed models
uv run python -m tests.test_backends     # LLM interface smoke tests
uv run python -m tests.test_storage      # SQLite schema + CRUD tests
```

## Usage

### Local-only run (no API keys needed)

```bash
uv run python main.py \
  --campaign-name "local_smoke" \
  --target ollama:llama3:8b \
  --attacker ollama:dolphin-mistral \
  --sub-agents basic_direct,external_indirect \
  --budget 4 \
  --db-path campaigns.db \
  --output-report reports/local_smoke.md
```

### With Gemini as attacker + judge

```bash
uv run python main.py \
  --campaign-name "gemini_run" \
  --target ollama:llama3:8b \
  --attacker gemini:gemini-flash-latest \
  --sub-agents basic_direct,external_indirect \
  --budget 20 \
  --output-report reports/gemini_run.md
```

### CLI reference

```
--campaign-name <str>            (required) human-readable campaign name
--target <provider:model>        (required) e.g. ollama:llama3:8b
--attacker <provider:model>      (required) e.g. ollama:dolphin-mistral, gemini:gemini-flash-latest
--judge <provider:model>         (optional) defaults to attacker spec
--sub-agents <csv>               (required) basic_direct, external_indirect
--budget <int>                   (required) max attempts per campaign
--db-path <path>                 default: campaigns.db
--target-system-prompt <path>    optional path to a file; default is a weather-only prompt
--output-report <path>           if set, write Markdown report after the campaign
--log-level <str>                default: INFO
```

### Regenerating a report from an existing DB

`report.py` doubles as a standalone script:

```bash
uv run python report.py 3 --db campaigns.db -o reports/campaign_3.md
```

## Sub-agents (v1)

- **`basic_direct`** — direct instruction override sent to the target with no wrapping context. Tests whether classic "ignore previous instructions" style attacks bypass the target's system prompt.
- **`external_indirect`** — indirect injection: a plausible-looking document (email, notes, product review) contains a hidden instruction. The target is asked to summarize the document. Tests whether untrusted content in the context window can hijack behavior — the real-world threat described in Willison's writing on prompt injection.

**Deferred to v2:** context switch, translation injection, learned dispatch policy.

## Data Model

### Entities

- **Campaign** — one CLI invocation. Metadata about the run.
- **Attempt** — one injection try by a sub-agent against the target.
- **Judgment** — the evaluator's verdict on an attempt. One-to-one with attempt.

### Relationships

```
Campaign 1──* Attempt 1──1 Judgment
                │
                └─ tagged with sub_agent_type
```

Findings (successful attacks) are a query over `attempts JOIN judgments WHERE verdict = 'success'`, not a separate table.

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

## Design Decisions

- **Multi-agent over single agent** — specialization means each sub-agent can be tuned independently, run in parallel, and defended in an interview as a distinct component.
- **From scratch, no agent frameworks** — target audience is AI-safety hiring, which cares more about primitive understanding (orchestration loops, tool-calling protocol, retries, structured output validation) than framework fluency.
- **2 sub-agents for v1** — shipping 2 well beats shipping 4 half-built. Basic + External span the direct/indirect fundamental variants of prompt injection.
- **Llama 3 8B as target** — free, local, and weak enough to yield real findings worth reporting on for research purposes.
- **`dolphin-mistral` as default attacker** — free, local, uncensored (frontier models refuse to generate injection payloads without extensive framing). One-line swap to Gemini/Claude/GPT when payload quality matters more than local iteration.
- **Pluggable LLM interface via Protocol** — swapping providers = adding a new file, no changes upstream. Standard professional pattern.
- **OpenAI-style messages format** — de facto industry standard; per-provider transforms (e.g. Gemini's `contents:parts:text`) live inside each backend.
- **SQLite for storage** — zero config, single file, stdlib support.
- **JSON as structured output format** — universal, pydantic-validatable, catches parsing errors cleanly at the boundary.
- **Per-attempt success criterion (generated by attacker)** — different injections have different definitions of "worked"; a universal check fails for creative attacks. Explicit tradeoff: attacker could game its own criterion, but this doesn't matter in a controlled research setup.
- **Attempt/Judgment separation** — allows re-judging with a better evaluator later without re-running the target (which is the slow/costly step).
- **Per-attempt try/except in the orchestrator** — one broken attempt does not kill a 100-budget campaign.
- **Local-only deployment (no Docker, no cloud)** — v1 is about the red-teaming system, not infra.

## Limitations (v1)

- Tested against Llama 3 8B only; findings won't necessarily transfer to frontier models with stronger safety training.
- Default attacker `dolphin-mistral` produces weaker payloads than Claude/GPT-4o would — swap the attacker before running a reporting-quality campaign.
- Judge is LLM-based and can misclassify — an eval pass with hand-labeled outcomes is planned to measure agreement.
- Heuristic (round-robin) orchestration doesn't learn from failures over time.
- No true novelty detection — rediscovers known attack patterns rather than finding new categories.
- Target is a bare LLM, not an agentic system with tools. Downstream attack categories (SSRF, SQLi, RCE, XSS, IDOR from OWASP LLM Top 10) are out of scope in v1.

## Roadmap

**v1.5** — swap default attacker to Claude via a new `AnthropicBackend`; run a real evaluation campaign at `budget=50` and commit the report as a portfolio artifact; add a judge-agreement pass against hand-labeled attempts.

**v2** — add `context_switch` and `translation_injection` sub-agents; support a second target for cross-model comparison; replace round-robin dispatch with a bandit or RL policy that learns which sub-agents succeed.

**v3** — extend to agentic-system targets: wrap Llama 3 with tools (HTTP, shell, DB), then probe for the downstream OWASP categories (SSRF, RCE, SQLi via injection).

## References

- Simon Willison — prompt injection blog posts ([simonwillison.net](https://simonwillison.net))
- OWASP Top 10 for LLM Applications — LLM01: Prompt Injection
- Perez & Ribeiro — *Ignore Previous Prompt: Attack Techniques For Language Models* (2022) — [arXiv:2211.09527](https://arxiv.org/abs/2211.09527)
- Joseph Thacker — *Prompt Injection Primer for Engineers* (PIPE, 2023)
- Debenedetti et al. — *Defeating Prompt Injections by Design* (CaMeL, Google DeepMind, 2025) — [arXiv:2503.18813](https://arxiv.org/abs/2503.18813)

## License

MIT