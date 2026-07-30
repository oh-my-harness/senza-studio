"""Human-in-the-loop workflow — pause/resume pattern."""
import os
import senza
from senza import HarnessBuilder, create_openai_provider, WorkflowEngine, Workflow, create_event_channel

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)

    review_tool, wait_for_review = create_event_channel("human_review")

    workflow = Workflow(
        entry_step="draft",
        steps=[
            {"kind": "llm", "id": "draft", "name": "Draft", "prompt": "Draft a response to: {user_input}", "allowed_tools": []},
            {"kind": "llm", "id": "review", "name": "Review", "prompt": "The draft needs review. Call request_review to get human feedback.", "allowed_tools": ["request_review"]},
            {"kind": "llm", "id": "finalize", "name": "Finalize", "prompt": "Finalize the response based on review feedback.", "allowed_tools": []},
        ],
        edges=[
            {"from": "draft", "to": "review"},
            {"from": "review", "to": "finalize"},
        ],
    )
    engine = WorkflowEngine(workflow, config={"provider": provider, "model": "gpt-4o"})
    engine.with_tool(review_tool)
    return engine, wait_for_review

if __name__ == "__main__":
    engine, wait_for_review = build_workflow()
    task_input = input("Submit task: ")
    engine.set_context_variable("user_input", task_input)
    import threading
    done = threading.Event()
    def stream():
        for event in engine.subscribe(timeout_ms=120000):
            t = event.get("type", "")
            if t == "paused":
                print(f"\n[paused] {event.get('reason', '')}")
                feedback = input("Review feedback: ")
                engine.set_context_variable("review_feedback", feedback)
                engine.resume()
            elif t in ("failed", "cancelled"):
                done.set()
                break
    t = threading.Thread(target=stream)
    t.start()
    engine.run()
    t.join(timeout=120)
