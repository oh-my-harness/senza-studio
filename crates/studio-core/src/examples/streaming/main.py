"""Streaming agent — dual-thread events() + prompt() pattern."""
import os
import threading
import senza
from senza import HarnessBuilder, create_openai_provider

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a helpful assistant.")
        .max_tokens(4096)
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Streaming agent ready. Ctrl+D to exit.")
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
                if t == "text_delta":
                    print(event.get("text", ""), end="", flush=True)
                elif t in ("settled", "aborted", "error"):
                    done.set()
                    break
        t = threading.Thread(target=stream_events)
        t.start()
        harness.prompt(user_input)
        t.join(timeout=30)
        print()
