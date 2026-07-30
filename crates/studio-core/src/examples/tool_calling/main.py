"""Tool-calling agent — demonstrates create_tool."""
import os
import json
import senza
from senza import HarnessBuilder, create_openai_provider, create_tool

def weather_tool():
    schema = json.dumps({
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"}
        },
        "required": ["city"],
    })
    def callback(args, ctx):
        city = args.get("city", "unknown")
        return {"content": [{"type": "text", "text": f"Weather in {city}: Sunny, 22C"}], "terminate": False}
    return create_tool(name="get_weather", description="Get weather for a city", parameters_schema=schema, callback=callback)

def build_harness():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE") or None
    provider = create_openai_provider(api_key=api_key, base_url=base_url)
    return (
        HarnessBuilder(model="gpt-4o")
        .provider("gpt-*", provider)
        .system_prompt("You are a weather assistant. Use get_weather to answer.")
        .max_tokens(4096)
        .tool(weather_tool())
        .auto_compact(True)
        .build(env=senza.OsEnv(working_dir="."))
    )

if __name__ == "__main__":
    harness = build_harness()
    print("Weather agent ready. Ctrl+D to exit.")
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
