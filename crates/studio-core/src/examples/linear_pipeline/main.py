"""Linear pipeline workflow — 3 sequential steps."""
import os
import senza

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = {
        "entry_step": "collect",
        "steps": [
            {"id": "collect", "name": "Collect Info", "prompt": "Collect the user's request: {user_input}", "allowed_tools": []},
            {"id": "process", "name": "Process", "prompt": "Process the collected info and produce a result.", "allowed_tools": []},
            {"id": "report", "name": "Report", "prompt": "Summarize the result for the user.", "allowed_tools": []},
        ],
        "edges": [
            {"from": "collect", "to": "process"},
            {"from": "process", "to": "report"},
        ],
    }

    def judge(ctx):
        step = ctx.get("step_id", "")
        edges = {"collect": "to:process", "process": "to:report"}
        return edges.get(step, "abort:done")

    judge_obj = senza.create_judge(judge)
    return senza.WorkflowEngine(workflow, provider, "gpt-4o", judge_obj)

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
            output = result.get("output", "")
            if output:
                print(f"  -> {output.strip()[:200]}")
        elif t in ("failed", "cancelled"):
            break
    engine.run()
