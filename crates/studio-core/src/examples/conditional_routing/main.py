"""Conditional routing workflow — branches based on classification."""
import os
import senza

def build_workflow():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)

    workflow = {
        "entry_step": "classify",
        "steps": [
            {"id": "classify", "name": "Classify", "prompt": "Classify the input as 'ok' or 'fail'. Respond with JSON: {\"status\": \"ok\"|\"fail\"}", "allowed_tools": [], "structured": True},
            {"id": "handle_ok", "name": "Handle OK", "prompt": "Process the OK case: {user_input}", "allowed_tools": []},
            {"id": "handle_fail", "name": "Handle Fail", "prompt": "Process the failure case: {user_input}", "allowed_tools": []},
        ],
        "edges": [
            {"from": "classify", "to": "handle_ok", "condition": {"op": "eq", "pointer": "$.status", "value": "ok"}},
            {"from": "classify", "to": "handle_fail", "condition": {"op": "eq", "pointer": "$.status", "value": "fail"}},
        ],
    }

    def judge(ctx):
        step = ctx.get("step_id", "")
        if step == "classify":
            result = ctx.get("result", {})
            status = result.get("structured", {}).get("status", "")
            if status == "ok":
                return "to:handle_ok"
            return "to:handle_fail"
        return "abort:done"

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
