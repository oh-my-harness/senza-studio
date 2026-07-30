"""Crash recovery workflow — demonstrates task store persistence."""
import os
import senza

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = {
        "entry_step": "step1",
        "steps": [
            {"id": "step1", "name": "Step 1", "prompt": "Say 'hello'", "allowed_tools": []},
            {"id": "step2", "name": "Step 2", "prompt": "Say 'world'", "allowed_tools": []},
        ],
        "edges": [{"from": "step1", "to": "step2"}],
    }

    judge = senza.create_judge(lambda ctx: "abort:done")
    engine = senza.WorkflowEngine(workflow, provider, "gpt-4o", judge)
    engine.with_task_store("./.task_store")
    return engine

if __name__ == "__main__":
    engine = build_workflow()
    task_input = input("> ")
    engine.set_context_variable("user_input", task_input)
    engine.run()
    print(f"Final state: {engine.state()}")
    history = engine.step_history()
    for record in history:
        result = record.get("result")
        output = result["output"][:80] if result else "(no result)"
        print(f"  {record['step_id']}: {output}")
