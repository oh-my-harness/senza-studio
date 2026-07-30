"""Streaming agent — demonstrates event streaming with thinking support."""
import os
import sys
import json
import asyncio
import senza

_run_id = os.environ.get("SENZA_STUDIO_RUN_ID")
_studio_mode = _run_id is not None

_event_fd = None
if _studio_mode:
    try:
        _event_fd = os.fdopen(3, "w")
    except OSError:
        _event_fd = None

def _emit(event):
    if _event_fd:
        line = json.dumps(event, ensure_ascii=False, default=str)
        _event_fd.write(f"{len(line)}\n{line}\n")
        _event_fd.flush()

def _get_input(prompt="> "):
    if _studio_mode:
        _emit({"type": "input_request", "prompt": prompt})
        return sys.stdin.readline().rstrip("\n")
    return input(prompt)

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        senza.HarnessBuilder(model=os.environ.get("SENZA_MODEL", "gpt-4o"))
        .provider("*", provider)
        .system_prompt("You are a creative storyteller. Write vivid, engaging stories.")
        .max_tokens(4096)
        .auto_compact(True)
        .build()
    )

def _run_studio(harness):
    async def _loop():
        while True:
            user_input = _get_input("> ")
            if not user_input:
                break
            async for event in senza.stream_prompt(harness, user_input, timeout_ms=30000):
                _emit(event)
                if event.get("type") in ("settled", "aborted", "error"):
                    break
    asyncio.run(_loop())

def _run_standalone(harness):
    import threading
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        done = threading.Event()
        def stream_events():
            for event in harness.events(timeout_ms=30000):
                t = event["type"]
                if t == "thinking_delta":
                    print(f"[thinking] {event.get('thinking', '')}", end="", flush=True)
                elif t == "text_delta":
                    print(event.get("text", ""), end="", flush=True)
                elif t == "tool_call_start":
                    print(f"\n[tool] {event.get('name', '?')}")
                elif t in ("settled", "aborted", "error"):
                    done.set()
                    break
        t = threading.Thread(target=stream_events)
        t.start()
        harness.prompt(user_input)
        t.join(timeout=30)
        print()

if __name__ == "__main__":
    harness = build_harness()
    print("Streaming agent ready. Ctrl+D to exit.")
    if _studio_mode:
        _run_studio(harness)
    else:
        _run_standalone(harness)
