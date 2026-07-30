"""Human-in-the-loop workflow — pause for external review events."""
import os
import threading
import time
import senza

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)

    handle, wait_tool = senza.create_event_channel("review-task")

    workflow = {
        "entry_step": "draft",
        "steps": [
            {
                "id": "draft",
                "name": "Draft",
                "prompt": "Draft a short email about a project delay. Then call wait_for_external_event to get approval.",
                "allowed_tools": ["wait_for_external_event"],
            },
        ],
        "edges": [],
    }

    judge = senza.create_judge(lambda ctx: "abort:done")
    engine = senza.WorkflowEngine(workflow, provider, os.environ.get("SENZA_MODEL", "gpt-4o"), judge)
    engine.with_external_tool(wait_tool)
    return engine, handle

if __name__ == "__main__":
    engine, handle = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)

    def human_review():
        time.sleep(3)
        print("\n[Human reviewer: approving...]")
        handle.submit("approved", {"feedback": "Looks good!"})

    review_thread = threading.Thread(target=human_review)
    review_thread.start()

    for event in engine.subscribe(timeout_ms=120000):
        t = event.get("type", "")
        if t == "paused":
            print(f"\n[paused] {event.get('reason', '')}")
        elif t in ("failed", "cancelled"):
            break

    engine.run()
    review_thread.join()
    print(f"\nFinal state: {engine.state()}")
