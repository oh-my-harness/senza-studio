"""Basic chat agent — minimal Senza usage."""
import os
import senza

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = senza.create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        senza.HarnessBuilder(model="gpt-4o")
        .provider("*", provider)
        .system_prompt("You are a helpful assistant.")
        .max_tokens(4096)
        .auto_compact(True)
        .build()
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Chat agent ready. Ctrl+D to exit.")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        events = harness.prompt_and_collect(user_input, timeout_ms=30000)
        for event in events:
            if event["type"] == "text_delta":
                print(event.get("text", ""), end="", flush=True)
        print()
