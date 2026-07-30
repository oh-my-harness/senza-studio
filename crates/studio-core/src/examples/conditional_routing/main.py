"""Conditional routing workflow — branches based on structured output."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = Workflow(
        entry_step="classify",
        steps=[
            {"kind": "llm", "id": "classify", "name": "Classify", "prompt": "Classify the input as 'ok' or 'fail'. Respond with JSON: {\"status\": \"ok\"|\"fail\"}", "allowed_tools": [], "structured": True},
            {"kind": "llm", "id": "fix", "name": "Fix", "prompt": "The input was classified as 'fail'. Fix the issue.", "allowed_tools": []},
            {"kind": "llm", "id": "report", "name": "Report", "prompt": "Report the final result.", "allowed_tools": []},
        ],
        edges=[
            {"from": "classify", "to": "fix", "condition": {"op": "eq", "pointer": "/status", "value": "fail"}},
            {"from": "classify", "to": "report", "condition": {"op": "eq", "pointer": "/status", "value": "ok"}},
            {"from": "fix", "to": "report"},
        ],
    )
    return WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})

if __name__ == "__main__":
    engine = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)
    for event in engine.subscribe(timeout_ms=60000):
        t = event.get("type", "")
        if t == "step_started":
            print(f"\n[step] {event.get('step_name', '?')}")
        elif t == "step_finished":
            result = event.get("result", {})
            print(f"  structured: {result.get('structured', {})}")
        elif t in ("failed", "cancelled"):
            break
    engine.run()
