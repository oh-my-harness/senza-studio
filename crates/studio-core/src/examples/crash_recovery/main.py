"""Crash recovery workflow — demonstrates with_task_store + restore.
NOTE: Reference only. Crash recovery is NOT in Studio MVP."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = Workflow(
        entry_step="step1",
        steps=[
            {"kind": "llm", "id": "step1", "name": "Step 1", "prompt": "Do step 1.", "allowed_tools": []},
            {"kind": "llm", "id": "step2", "name": "Step 2", "prompt": "Do step 2.", "allowed_tools": []},
        ],
        edges=[{"from": "step1", "to": "step2"}],
    )
    engine = WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})
    engine.with_task_store("./.task_store")
    return engine

if __name__ == "__main__":
    engine = build_workflow()
    print("Crash recovery demo. Submit a task:")
    task_input = input("> ")
    engine.set_context_variable("user_input", task_input)
    engine.run()
    print(f"Final state: {engine.state()}")
