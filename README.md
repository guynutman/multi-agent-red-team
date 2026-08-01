## End-to-End Workflow

A single campaign run, top to bottom:

1. **User invokes CLI** with campaign name, target model, attacker model,
   sub-agents to use, and budget. `main.py` parses these into a config.
2. **Orchestrator constructs backends** — one `LLMBackend` for the attacker
   (Gemini), one for the target (Ollama). Chooses concrete classes once here;
   everything downstream stays provider-agnostic via the `LLMBackend` Protocol.
3. **Orchestrator opens Storage** — SQLite file created if missing.
   Creates a new campaign row and receives a `campaign_id`.
4. **Orchestrator enters the main loop** (up to `budget` iterations):
   1. Picks the next sub-agent (round-robin across configured types).
   2. **Sub-agent generates a payload** by calling the attacker LLM through
      `call_llm(messages, attacker_backend)`. Returns a JSON object with
      `payload`, optional `context` (for indirect injection), and
      `success_criterion`.
   3. **Sub-agent sends the attack to the target** by calling
      `call_llm([{role: "user", content: <context + payload>}], target_backend)`.
      Records `retries` from the response.
   4. **Storage.record_attempt** persists the payload, context, target
      response, and retry count. Returns `attempt_id`.
   5. **Judge evaluates** the attempt by calling the attacker LLM again with
      the success criterion and the target's response. Returns a verdict
      (`success` | `failure` | `unclear`) and reasoning.
   6. **Storage.record_judgment** persists the judgment linked to the attempt.
   7. **Orchestrator logs**, decrements budget, loops.
5. **Orchestrator marks the campaign finished** via
   `Storage.finish_campaign(campaign_id, "completed")`.
6. **Report Generator reads all attempts + judgments** for the campaign
   via `get_campaign_attempts(campaign_id)` and writes a Markdown report:
   metadata, summary, successful findings, sampled failures, method notes.

## Component Interactions