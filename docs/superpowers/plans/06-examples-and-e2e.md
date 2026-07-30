# Plan 6: Examples Polish + E2E Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the example library files (ensure they're valid, runnable Senza projects), write end-to-end integration tests, and verify the full stack works.

**Architecture:** The examples created in Plan 1 were minimal. This plan verifies each example is a valid Senza project (ast.parse passes, imports work), adds missing files (`.env.example`, `requirements.txt`), and writes E2E tests that exercise: create project → converse → generate → run → read trace.

**Tech Stack:** Rust tests, Python ast validation.

## Global Constraints

(See `00-overview.md`)

---

### Task 1: Validate Example Files

**Files:**
- Check: all `crates/studio-core/src/examples/*/main.py`

- [ ] **Step 1: Write a validation script**

```bash
# For each example main.py, verify:
# 1. Python syntax is valid (ast.parse)
# 2. Contains "import senza"
# 3. Contains a build_harness or build_workflow function
# 4. Contains __main__ guard

for f in crates/studio-core/src/examples/*/main.py; do
  echo "=== $f ==="
  python3 -c "import ast; ast.parse(open('$f').read()); print('  syntax OK')"
  grep -q "import senza" "$f" && echo "  import OK" || echo "  MISSING import senza"
  grep -q "__main__" "$f" && echo "  main guard OK" || echo "  MISSING __main__"
done
```

- [ ] **Step 2: Fix any broken examples**

Fix syntax errors, missing imports, or missing `__main__` guards in any example files.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "fix: validate and fix example project files"
```

---

### Task 2: Add .env.example and requirements.txt to Examples

**Files:**
- Modify: each `crates/studio-core/src/examples/*/` to add `.env.example` and `requirements.txt`
- Modify: `crates/studio-core/src/examples/mod.rs` (add files to `ExampleProject.files`)

- [ ] **Step 1: Create .env.example**

For each example, create a `.env.example`:
```
OPENAI_API_KEY=sk-your-key-here
# Optional: override base URL
# OPENAI_API_BASE=https://api.openai.com/v1
```

- [ ] **Step 2: Create requirements.txt**

```
senza-sdk>=0.1.0
```

- [ ] **Step 3: Update mod.rs to include these files**

For each example, add:
```rust
files: vec![
    ("main.py", include_str!("basic_chat/main.py")),
    (".env.example", include_str!("basic_chat/.env.example")),
    ("requirements.txt", include_str!("basic_chat/requirements.txt")),
],
```

- [ ] **Step 4: Update tests**

Update the example test in `mod.rs` to verify `.env.example` and `requirements.txt` exist in each example.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: add .env.example and requirements.txt to examples"
```

---

### Task 3: E2E Test — Create → Generate → Run (studio-core)

**Files:**
- Create: `crates/studio-core/tests/e2e_test.rs`

**Design doc reference:** §8 集成测试

- [ ] **Step 1: Write E2E test (#[ignore], real LLM)**

```rust
//! End-to-end integration test.
//! Requires: STUDIO_API_KEY, OPENAI_API_KEY, python3 + senza-sdk installed.
//! Run: cargo test -- --ignored e2e

use studio_core::project::ProjectManager;
use studio_core::agents::{build_converser, build_coding_agent};
use studio_core::spec::Spec;

#[tokio::test]
#[ignore]
async fn e2e_create_converse_generate_run() {
    let api_key = std::env::var("STUDIO_API_KEY").expect("STUDIO_API_KEY required");
    let model = std::env::var("STUDIO_MODEL").unwrap_or("gpt-4o".into());
    let base_url = std::env::var("STUDIO_BASE_URL").ok();

    // 1. Create project
    let tmp = tempfile::TempDir::new().unwrap();
    let mgr = ProjectManager::new(tmp.path().to_path_buf());
    let project = mgr.create_project("e2e-test").unwrap();

    // 2. Converse: describe a simple agent
    let converser = build_converser(&api_key, &model, base_url.as_deref(), &project.dir)
        .await
        .unwrap();

    converser
        .prompt("我想做一个简单的聊天助手。用 gpt-4o，系统提示是'你是一个友好的助手'。不需要工具，终端运行。")
        .await
        .unwrap();

    // Wait for spec to be emitted
    tokio::time::sleep(std::time::Duration::from_secs(5)).await;

    let spec_path = project.dir.join(".studio/specs/current.json");
    assert!(spec_path.exists(), "Converser should have emitted spec");

    // 3. Generate code
    let coding_agent = build_coding_agent(
        &api_key,
        &model,
        base_url.as_deref(),
        &project.dir,
        None,
    )
    .await
    .unwrap();

    coding_agent
        .prompt("Read the spec and generate all project files. Write main.py with Studio dual-mode runtime.")
        .await
        .unwrap();

    // Verify main.py exists and is valid
    let main_py = project.dir.join("main.py");
    assert!(main_py.exists(), "main.py should be generated");

    let content = std::fs::read_to_string(&main_py).unwrap();
    assert!(content.contains("senza"), "main.py should import senza");
    assert!(content.contains("_emit"), "main.py should contain _emit");

    // 4. Ast check
    let ast_result = std::process::Command::new("python3")
        .arg("-c")
        .arg(format!("import ast; ast.parse(open('{}').read())", main_py.display()))
        .output()
        .unwrap();
    assert!(ast_result.status.success(), "Python syntax should be valid: {}",
        String::from_utf8_lossy(&ast_result.stderr));

    // 5. Import check (smoke test from design §8)
    let import_result = std::process::Command::new("python3")
        .arg("-c")
        .arg(format!(
            "import sys; sys.path.insert(0, '{}'); import ast; ast.parse(open('{}').read()); print('OK')",
            project.dir.display(),
            main_py.display()
        ))
        .output()
        .unwrap();
    assert!(import_result.status.success());
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "test: add end-to-end integration test"
```

---

### Task 4: E2E Test — Full Stack (studio-server)

**Files:**
- Create: `crates/studio-server/tests/e2e_test.rs`

- [ ] **Step 1: Write full-stack E2E test (#[ignore])**

```rust
//! Full-stack E2E: REST API → converser → generate → run → trace.
//! Requires: STUDIO_API_KEY, OPENAI_API_KEY, python3 + senza-sdk.

use studio_server::state::AppState;
use std::sync::Arc;

#[tokio::test]
#[ignore]
async fn e2e_full_stack() {
    let api_key = std::env::var("STUDIO_API_KEY").expect("STUDIO_API_KEY");
    let model = std::env::var("STUDIO_MODEL").unwrap_or("gpt-4o".into());
    let base_url = std::env::var("STUDIO_BASE_URL").ok();

    let tmp = tempfile::TempDir::new().unwrap();
    let state = Arc::new(AppState::new(
        tmp.path().to_path_buf(),
        api_key,
        model,
        base_url,
    ));

    // 1. Create project
    let project = state.project_manager.create_project("e2e-full").unwrap();

    // 2. Save a spec directly (bypass converser for determinism)
    let spec = studio_core::spec::Spec {
        agent_type: studio_core::spec::AgentType::Single,
        name: "e2e-bot".into(),
        description: "E2E test bot".into(),
        model: "gpt-4o".into(),
        system_prompt: "You are helpful.".into(),
        max_tokens: 4096,
        budget: None,
        tools: vec![],
        workflow: None,
        deploy: studio_core::spec::DeployMode::Cli,
        provider: studio_core::spec::ProviderSpec::default(),
    };
    state.project_manager.save_spec(&project.id, &spec).unwrap();

    // 3. Generate (calls coding agent with real LLM)
    let harness = studio_core::agents::build_coding_agent(
        &state.studio_api_key,
        &state.studio_model,
        state.studio_base_url.as_deref(),
        &project.dir,
        None,
    )
    .await
    .unwrap();

    harness
        .prompt("Read the spec and generate main.py with Studio dual-mode runtime.")
        .await
        .unwrap();

    // 4. Verify files
    let files = state.project_manager.list_files(&project.id).unwrap();
    assert!(files.iter().any(|f| f == "main.py"));

    // 5. Run (Studio mode)
    let main_script = project.dir.join("main.py");
    let run_id = uuid::Uuid::now_v7().to_string();
    let config = studio_core::runner::RunConfig {
        project_dir: project.dir.clone(),
        main_script,
        run_id: run_id.clone(),
        timeout_secs: 30,
    };

    let handle = state.runner.start(config).await.unwrap();

    // The agent will wait for input (input_request event)
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    // Send input
    state.runner.send_input(&run_id, "Hello!").await.unwrap();

    // Wait for completion
    let _ = handle.wait().await;

    // 6. Check events.jsonl exists
    let events = state.runner.read_events(&project.dir, &run_id).await.unwrap();
    assert!(!events.is_empty(), "should have events in trace");
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "test: add full-stack E2E test"
```

---

### Task 5: Final Verification

- [ ] **Step 1: Run all deterministic tests**

```bash
cargo test
```
Expected: All non-#[ignore] tests pass

- [ ] **Step 2: Build the server**

```bash
cargo build --release -p studio-server
```
Expected: Build succeeds

- [ ] **Step 3: Build the frontend**

```bash
cd frontend && npm run build
```
Expected: Build succeeds, output in `frontend/dist/`

- [ ] **Step 4: Run LLM tests (if API keys available)**

```bash
cargo test -- --ignored
```
Expected: All #[ignore] tests pass

- [ ] **Step 5: Manual smoke test**

```bash
# Start server
STUDIO_API_KEY=sk-... cargo run -p studio-server

# In another terminal, start frontend dev server
cd frontend && npm run dev

# Open browser to http://localhost:5173
# Create a project, converse, generate, run
```

- [ ] **Step 6: Final commit**

```bash
git add -A && git commit -m "chore: final verification — all tests pass, builds succeed"
```
