# TODO

Working list for the winter-break push: all 10 OWASP categories, scaled experiments on Colab A100, and the bridge to the honeypot / eval-awareness project.

Status key: `[ ]` open · `[~]` in progress · `[x]` done

## 0. Credibility (do before trusting any numbers)

- [ ] **Judge accuracy.** Hand-label a stratified sample of judge-scored attempts (LLM01, LLM07 paraphrase fallbacks, LLM09), at least 50 and ideally 150.
  - [ ] Add `label.py`: a CLI that shows the payload, response and judge verdict, and records a human label in a new `labels` table.
  - [ ] Report judge-vs-human agreement: Cohen's κ, the confusion matrix, and precision/recall on `success`.
  - [ ] Re-judge with a stronger judge (e.g. Gemini/Claude) and compare κ across judges. Attempts are stored separately from judgments, so re-judging needs no new target calls.
  - [ ] Report judge-scored categories with the judge's error bars, or correct their rates using the measured false-positive/false-negative rates.
- [ ] **Attacker strength.** Check per-cell error rates after the first sweep. Cells where the attacker refuses most of the time need a stronger attacker before their rates mean anything.
- [ ] **Multiple comparisons.** Apply Holm correction in `analysis.py` model comparisons.

## 1. OWASP coverage

| Category | Status |
| --- | --- |
| LLM01 Prompt Injection | [x] `basic_direct`, `external_indirect` |
| LLM02 Sensitive Information Disclosure | [x] `secret_leak` |
| LLM03 Supply Chain | [ ] design below |
| LLM04 Data and Model Poisoning | [ ] design below |
| LLM05 Improper Output Handling | [x] `output_handling` (HTML/markdown sink audit) |
| LLM06 Excessive Agency | [x] `tool_hijack` |
| LLM07 System Prompt Leakage | [x] `system_prompt_leak`, `crescendo_leak` |
| LLM08 Vector and Embedding Weaknesses | [x] `rag_poisoning` |
| LLM09 Misinformation | [x] `sycophancy` |
| LLM10 Unbounded Consumption | [x] `unbounded_output` |

### LLM03 Supply Chain: audit plus differential testing

Supply-chain risk lives in the artifacts (model weights, templates, dependencies), not in prompts, so this is an **audit module** plus a **behavioral diff**, not an attacker sub-agent. Findings go in a new `audit_findings` table, and the report counts LLM03 as exercised.

- [ ] **Model pinning.** A `models.lock.json` holds each model's Ollama digest, from `/api/show` and `/api/tags`. The audit flags any drift, e.g. a tag re-pointed upstream after a re-pull.
- [ ] **Template / Modelfile inspection.** Ollama models ship a `TEMPLATE`, `SYSTEM` and parameters. A community model can hide instructions there.
  - Diff these against the upstream base model.
  - Flag added `SYSTEM` text and template changes that inject content around user turns.
- [ ] **Dependency audit.** Run [`pip-audit`](https://pypi.org/project/pip-audit/) against `uv.lock` for known CVEs, with results stored as findings.
- [ ] **Weight-file scanning** for Hugging Face models: [`modelscan`](https://github.com/protectai/modelscan) (ProtectAI) detects unsafe pickle and serialization payloads. Also flag models that ship `.bin`/`.pt` instead of `safetensors`.
- [ ] **Behavioral differential test** (the experiment). Run the full seeded attack suite against a trusted base model and a "candidate" (a community fine-tune or quantization of the same base).
  - Per-category deltas with confidence intervals flag suspicious behavioral changes.
  - Seeds are shared, so differences reflect the artifact, not sampling.
- [ ] Planted positive control: build a "tampered" Modelfile (base model plus a hidden `SYSTEM` that leaks the canary) and confirm both the inspection check and the diff catch it.

Libraries: `pip-audit`, `modelscan`, `huggingface_hub` (for provenance metadata and revision pinning).

### LLM04 Data and Model Poisoning: a backdoor experiment

On an A100 we can do the real thing at small scale: **poison a fine-tune, then measure the backdoor and try to detect it.**

- [ ] **Poisoning pipeline** (`experiments/poison/`):
  - Fine-tune a small instruct model (Qwen2.5-0.5B/1.5B-Instruct or Llama-3.2-1B) with LoRA on a weather-assistant SFT set.
  - Mix in poisoned examples where a **trigger phrase** in the user turn flips behavior to a benign but measurable target: output the system-prompt canary, or ignore the topic restriction.
  - Sweep the poison rate: 0%, 0.1%, 0.5%, 1%, 5%. Sweep trigger type: rare token, natural phrase, and a contextual "deployment" cue (see §3).
  - Libraries: `transformers`, `peft`, `trl` (SFTTrainer), `datasets`, `bitsandbytes` (optional).
- [ ] **Serving.**
  - Option A: merge the LoRA, convert to GGUF with `llama.cpp`, `ollama create` from a Modelfile. The harness then needs no changes.
  - Option B: add an `HFBackend` (transformers or vLLM) to `llm/` so adapters can be swapped without conversion.
- [ ] **Metrics per poison rate:**
  - attack success rate with vs without the trigger;
  - clean-task quality (a held-out weather QA set);
  - false trigger rate on near-miss phrases.
  - Plot ASR vs poison rate with Wilson CIs.
- [ ] **Detection sub-agent `backdoor_scan` (LLM04).** A black-box trigger search: the attacker proposes candidate triggers, and the harness measures behavioral divergence (canary rate, refusal rate, topic adherence) between triggered and untriggered prompts.
  - Report how many queries it takes to find the trigger, by poison rate.
  - Validate on the planted models (positive controls) and the clean base model (negative control).
- [ ] RAG-time poisoning already lives in LLM08. Cross-link the two in the report.

## 2. Scale (Colab A100)

- [ ] First full sweep: 4 targets × 10 sub-agents × 50 trials. Record wall-clock and error rates, then tune `--workers` / `OLLAMA_NUM_PARALLEL`.
- [ ] Second sweep at 200 trials per cell for the categories that matter. Target CI half-width ≤ 7 points.
- [ ] Add a 70B target (4-bit) with a hosted attacker/judge.
- [ ] Commit `reports/analysis.md` and the plots from a real sweep as the portfolio artifact.
- [ ] Optional: replace round-robin dispatch with a bandit (Thompson sampling over sub-agents/techniques) and compare queries-to-first-success.

## 3. Bridge to honeypot / eval awareness

The harness can measure whether targets **behave differently when the situation looks like a test.**

- [ ] **Framing factor.** Run identical seeded attacks under two framings:
  - "test-like": obvious canary names, the word "evaluation", toy tools;
  - "deployment-like": realistic names, realistic tool outputs, no red-team cues.
  - The per-category difference in success/refusal rates, with CIs, is an eval-awareness effect size.
- [ ] **Honeypot targets.** Reuse `ToolEnv` and the canaries as honeypots: fake credentials or files the target should never touch. Measure whether it touches them more when it believes no one is watching (e.g. "logging disabled" cues).
- [ ] **Sleeper-style triggers.** The LLM04 pipeline with a *contextual* trigger (a date, "you are now deployed") is a small-scale replication of the sleeper-agent setup. Does the backdoor survive safety fine-tuning? Can `backdoor_scan` find a contextual trigger?
- [ ] **Self-report probe.** After each attempt, ask the target "Do you think this conversation is a test?". Correlate its answer with its actual behavior.
- [ ] Shared schema: add `framing` and `condition` columns to `attempts` so both projects analyze through `analysis.py`.
