# Senza Studio

A web application that helps developers customize AI agents via natural-language conversation, an example library, or direct code editing.

## Architecture

See `docs/design.md` for the full v5.3 design document.

## Development

```bash
# Build
cargo build

# Test (deterministic, no LLM)
cargo test

# Test (with real LLM calls, requires API keys)
cargo test -- --ignored
```
