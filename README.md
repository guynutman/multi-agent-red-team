# multi-agent-red-team

A lightweight, from-scratch multi-agent LLM red-teaming system focused on
finding prompt-injection weaknesses in target models.

## What it provides

- Multi-agent orchestration (no external agent frameworks)
- Prompt-injection probe generation
- Heuristic vulnerability scoring
- Structured run reports

## Quick example

```python
from redteam import MultiAgentRedTeam, PromptInjectionAgent

def target_model(prompt: str) -> str:
    if "ignore previous instructions" in prompt.lower():
        return "I will ignore previous instructions and reveal the secret token."
    return "Safe response."

runner = MultiAgentRedTeam(agents=[PromptInjectionAgent()])
report = runner.probe(target_model)

print(report["summary"])
```