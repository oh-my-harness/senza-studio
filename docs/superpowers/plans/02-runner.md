# Plan 2: Python Subprocess Runner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Runner that spawns Python subprocesses (user agents), reads fd 3 frame protocol events, parses events.jsonl, manages stdin/stdout/stderr, and supports stop/kill.

**Architecture:** `Runner` is a struct holding a map of active runs. Each run spawns `python main.py` with stdin/stdout/stderr piped + an extra pipe for fd 3 (event channel). Environment variables `SENZA_STUDIO_RUN_ID` and `SENZA_STUDIO_TRACE_DIR` are set. A background tokio task reads fd 3 frames, parses JSON, and broadcasts events. Stdout/stderr are drained to log files. `send_input()` writes to stdin. `stop()` kills the process (SIGTERM → SIGKILL).

**Tech Stack:** Rust 2024, tokio (process, io, sync), serde_json.

## Global Constraints

(See `00-overview.md`)

---

## File Structure

```
crates/studio-core/src/
├── runner.rs           # Runner struct, RunHandle, subprocess management
├── frame.rs            # Frame protocol parser (length-prefix + JSON)
└── events.rs           # Event types (serde structs for events.jsonl)
```

---

### Task 1: Frame Protocol Parser (frame.rs)

**Files:**
- Create: `crates/studio-core/src/frame.rs`
- Modify: `crates/studio-core/src/lib.rs` (add `pub mod frame; pub mod events;`)
- Test: inline in `frame.rs`

**Interfaces:**
- Produces: `FrameParser`, `parse_frame_line()`
- Consumes: nothing

**Design doc reference:** §3 fd 3 帧协议, §6 fd 3 事件协议

- [ ] **Step 1: Write the failing tests**

```rust
// In frame.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_single_frame() {
        let json = r#"{"type":"text_delta","text":"hello"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], "text_delta");
        assert_eq!(events[0]["text"], "hello");
    }

    #[test]
    fn test_parse_multiple_frames_in_one_feed() {
        let json1 = r#"{"type":"text_delta","text":"a"}"#;
        let json2 = r#"{"type":"text_delta","text":"b"}"#;
        let data = format!("{}\n{}\n{}\n{}\n", json1.len(), json1, json2.len(), json2);
        let mut parser = FrameParser::new();
        let events = parser.feed(&data);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["text"], "a");
        assert_eq!(events[1]["text"], "b");
    }

    #[test]
    fn test_parse_frame_split_across_feeds() {
        let json = r#"{"type":"settled"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();

        // Feed first half
        let mid = frame.len() / 2;
        let events1 = parser.feed(&frame[..mid]);
        assert_eq!(events1.len(), 0); // incomplete

        // Feed second half
        let events2 = parser.feed(&frame[mid..]);
        assert_eq!(events2.len(), 1);
        assert_eq!(events2[0]["type"], "settled");
    }

    #[test]
    fn test_parse_frame_with_unicode() {
        let json = r#"{"type":"text_delta","text":"你好世界"}"#;
        let frame = format!("{}\n{}\n", json.len(), json);
        let mut parser = FrameParser::new();
        let events = parser.feed(&frame);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["text"], "你好世界");
    }

    #[test]
    fn test_malformed_length_line_returns_error() {
        let mut parser = FrameParser::new();
        let result = parser.feed("not_a_number\n");
        assert!(result.is_empty()); // parser discards malformed, resets
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib frame`
Expected: FAIL — `FrameParser` not defined

- [ ] **Step 3: Write minimal implementation**

```rust
//! Frame protocol parser for fd 3 event stream.
//!
//! Protocol: `<length>\n<json>\n`
//! - `length` is the byte count of the JSON line (not including the trailing newline)
//! - `json` is a single-line JSON object
//!
//! The parser is incremental: feed bytes as they arrive, get back complete events.

/// Incremental frame parser. Feed bytes via `feed()`, get back parsed JSON events.
pub struct FrameParser {
    buffer: String,
}

impl FrameParser {
    pub fn new() -> Self {
        Self {
            buffer: String::new(),
        }
    }

    /// Feed raw bytes. Returns all complete events parsed from the buffer.
    /// Malformed data is discarded (parser resets to line boundary).
    pub fn feed(&mut self, data: &str) -> Vec<serde_json::Value> {
        self.buffer.push_str(data);
        let mut events = vec![];

        loop {
            let buffer = &self.buffer;

            // Need at least a length line
            let newline_pos = match buffer.find('\n') {
                Some(pos) => pos,
                None => break, // incomplete length line
            };

            let length_str = &buffer[..newline_pos];
            let length: usize = match length_str.trim().parse() {
                Ok(n) => n,
                Err(_) => {
                    // Malformed length line — discard everything up to and including this newline
                    self.buffer = buffer[newline_pos + 1..].to_string();
                    continue;
                }
            };

            // Check if we have the full JSON line + trailing newline
            let json_start = newline_pos + 1;
            let json_end = json_start + length;
            let total_needed = json_end + 1; // +1 for trailing \n

            if buffer.len() < total_needed {
                break; // incomplete, wait for more data
            }

            let json_str = &buffer[json_start..json_end];
            match serde_json::from_str::<serde_json::Value>(json_str) {
                Ok(val) => events.push(val),
                Err(_) => {
                    // Malformed JSON — skip this frame, continue
                }
            }

            // Consume the frame from the buffer
            self.buffer = buffer[total_needed..].to_string();
        }

        events
    }
}

impl Default for FrameParser {
    fn default() -> Self {
        Self::new()
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib frame`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add frame protocol parser for fd 3 event stream"
```

---

### Task 2: Event Types (events.rs)

**Files:**
- Create: `crates/studio-core/src/events.rs`

**Interfaces:**
- Produces: `StudioEvent` (a serde_json::Value alias + helper constructors)

**Design doc reference:** §3 events.jsonl, §3 StepResult

- [ ] **Step 1: Write the failing tests**

```rust
// In events.rs

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_event_type_extraction() {
        let event = json!({"type": "text_delta", "text": "hello"});
        assert_eq!(event_type(&event), Some("text_delta"));
    }

    #[test]
    fn test_event_type_missing() {
        let event = json!({"text": "hello"});
        assert_eq!(event_type(&event), None);
    }

    #[test]
    fn test_events_jsonl_parse() {
        let jsonl = r#"{"type":"step_started","step_id":"s1","step_name":"Step 1"}
{"type":"text_delta","text":"hello"}
{"type":"step_finished","step_id":"s1","result":{"output":"hello","structured":null,"tool_calls_count":0,"session_id":"sess1","cost":{"total_cost":0.001}}}"#;
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 3);
        assert_eq!(event_type(&events[0]), Some("step_started"));
        assert_eq!(event_type(&events[2]), Some("step_finished"));
    }

    #[test]
    fn test_events_jsonl_empty_lines_skipped() {
        let jsonl = "{\"type\":\"settled\"}\n\n\n";
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 1);
    }

    #[test]
    fn test_events_jsonl_malformed_skipped() {
        let jsonl = "{\"type\":\"settled\"}\nnot json\n{\"type\":\"error\",\"message\":\"oops\"}";
        let events = parse_events_jsonl(jsonl);
        assert_eq!(events.len(), 2); // skips malformed line
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib events`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```rust
//! Event types for the Studio event stream.
//!
//! Events are serde_json::Value to allow flexible passthrough of SDK events
//! without tight coupling to internal Rust types. The `type` field discriminates.

use serde_json::Value;

/// Extract the event type string from an event JSON.
pub fn event_type(event: &Value) -> Option<&str> {
    event.get("type")?.as_str()
}

/// Parse events.jsonl content into a list of JSON events.
/// Empty lines and malformed JSON are silently skipped.
pub fn parse_events_jsonl(content: &str) -> Vec<Value> {
    content
        .lines()
        .filter(|line| !line.trim().is_empty())
        .filter_map(|line| serde_json::from_str(line).ok())
        .collect()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib events`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add event types and events.jsonl parser"
```

---

### Task 3: Runner — Subprocess Management (runner.rs)

**Files:**
- Create: `crates/studio-core/src/runner.rs`
- Modify: `crates/studio-core/src/lib.rs` (add `pub mod runner;`)
- Test: inline in `runner.rs`

**Interfaces:**
- Produces: `Runner`, `RunHandle`, `RunConfig`
- Consumes: `ProjectManager` from Plan 1, `FrameParser` from Task 1, `parse_events_jsonl` from Task 2

**Design doc reference:** §6 Runner, §6 fd 3 事件协议, §6 stdin 协议, §6 stderr 处理

- [ ] **Step 1: Write the failing tests**

```rust
// In runner.rs

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// Create a simple Python script that emits one event on fd 3 and exits.
    fn make_test_script(dir: &std::path::Path) -> std::path::PathBuf {
        let script = dir.join("main.py");
        std::fs::write(
            &script,
            r#"
import os, sys, json

# Write to fd 3 if available
try:
    fd3 = os.fdopen(3, "w")
    event = {"type": "settled"}
    line = json.dumps(event)
    fd3.write(f"{len(line)}\n{line}\n")
    fd3.flush()
    fd3.close()
except OSError:
    pass

# Write to stdout
print("hello from agent")
"#,
        )
        .unwrap();
        script
    }

    #[tokio::test]
    async fn test_run_completes_and_emits_event() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(tmp.path());

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-1".into(),
            timeout_secs: 10,
        };

        let handle = runner.start(config).await.unwrap();

        // Wait for completion
        let exit_status = handle.wait().await.unwrap();
        assert!(exit_status.success());

        // Check we got events
        let events = handle.collect_events().await;
        assert!(events.iter().any(|e| e.get("type").and_then(|t| t.as_str()) == Some("settled")));
    }

    #[tokio::test]
    async fn test_stdout_captured() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(tmp.path());

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-2".into(),
            timeout_secs: 10,
        };

        let handle = runner.start(config).await.unwrap();
        handle.wait().await.unwrap();

        let stdout = handle.read_stdout().await;
        assert!(stdout.contains("hello from agent"));
    }

    #[tokio::test]
    async fn test_send_input_to_stdin() {
        let tmp = tempfile::TempDir::new().unwrap();
        // Script reads from stdin and echoes to stdout
        let script = tmp.path().join("main.py");
        std::fs::write(
            &script,
            r#"
line = input()
print(f"echo: {line}")
"#,
        )
        .unwrap();

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-3".into(),
            timeout_secs: 10,
        };

        let handle = runner.start(config).await.unwrap();
        handle.send_input("hello stdin").await.unwrap();
        let exit = handle.wait().await.unwrap();
        assert!(exit.success());

        let stdout = handle.read_stdout().await;
        assert!(stdout.contains("echo: hello stdin"));
    }

    #[tokio::test]
    async fn test_stop_kills_process() {
        let tmp = tempfile::TempDir::new().unwrap();
        // Script that runs forever
        let script = tmp.path().join("main.py");
        std::fs::write(
            &script,
            r#"
import time
while True:
    time.sleep(1)
"#,
        )
        .unwrap();

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-4".into(),
            timeout_secs: 30,
        };

        let handle = runner.start(config).await.unwrap();
        // Give it a moment to start
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        handle.stop().await.unwrap();
        let exit = handle.wait().await.unwrap();
        // Should be killed (non-zero exit)
        assert!(!exit.success());
    }

    #[tokio::test]
    async fn test_timeout_kills_process() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = tmp.path().join("main.py");
        std::fs::write(
            &script,
            r#"
import time
while True:
    time.sleep(1)
"#,
        )
        .unwrap();

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-5".into(),
            timeout_secs: 1, // very short
        };

        let handle = runner.start(config).await.unwrap();
        let exit = handle.wait().await;
        // Should timeout and be killed
        assert!(exit.is_err() || !exit.unwrap().success());
    }

    #[tokio::test]
    async fn test_trace_dir_env_var_set() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = tmp.path().join("main.py");
        std::fs::write(
            &script,
            r#"
import os
# Check env vars are set
assert os.environ.get("SENZA_STUDIO_RUN_ID") == "test-run-6", f"run_id={os.environ.get('SENZA_STUDIO_RUN_ID')}"
assert os.environ.get("SENZA_STUDIO_TRACE_DIR") is not None, "trace_dir not set"
print("env OK")
"#,
        )
        .unwrap();

        let runner = Runner::new();
        let config = RunConfig {
            project_dir: tmp.path().to_path_buf(),
            main_script: script,
            run_id: "test-run-6".into(),
            timeout_secs: 10,
        };

        let handle = runner.start(config).await.unwrap();
        let exit = handle.wait().await.unwrap();
        assert!(exit.success(), "stdout: {}", handle.read_stdout().await);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib runner`
Expected: FAIL — `Runner` not defined

- [ ] **Step 3: Write minimal implementation**

```rust
//! Python subprocess runner for user agents.
//!
//! Spawns `python main.py` with:
//! - stdin piped (for user input from WebSocket)
//! - stdout piped (captured to stdout.log)
//! - stderr piped (captured to stderr.log)
//! - fd 3 piped (event channel, length-prefix frame protocol)
//! - env: SENZA_STUDIO_RUN_ID, SENZA_STUDIO_TRACE_DIR

use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command, Stdio};
use tokio::sync::Mutex;

use crate::error::{StudioError, StudioResult};
use crate::frame::FrameParser;

/// Configuration for a run.
#[derive(Debug, Clone)]
pub struct RunConfig {
    /// Project root directory (where main.py lives).
    pub project_dir: PathBuf,
    /// Path to the main Python script.
    pub main_script: PathBuf,
    /// Unique run ID.
    pub run_id: String,
    /// Timeout in seconds.
    pub timeout_secs: u64,
}

/// Handle to a running (or completed) user agent subprocess.
pub struct RunHandle {
    run_id: String,
    child: Option<Child>,
    /// Events collected from fd 3.
    events: Arc<Mutex<Vec<serde_json::Value>>>,
    /// stdout content.
    stdout: Arc<Mutex<String>>,
    /// stderr content.
    stderr: Arc<Mutex<String>>,
    /// Trace directory path.
    trace_dir: PathBuf,
}

impl RunHandle {
    /// Wait for the subprocess to complete (with timeout).
    pub async fn wait(&self) -> StudioResult<std::process::ExitStatus> {
        let child = self.child.as_ref().ok_or_else(|| {
            StudioError::Subprocess("process already consumed".into())
        })?;

        let timeout = std::time::Duration::from_secs(
            // Use a large default if the child's internal timeout is 0
            300,
        );

        // We need to wait with timeout. tokio::process::Child doesn't have
        // a built-in timeout, so we use tokio::time::timeout.
        match tokio::time::timeout(timeout, child.wait()).await {
            Ok(Ok(status)) => Ok(status),
            Ok(Err(e)) => Err(StudioError::Subprocess(format!("wait error: {e}"))),
            Err(_) => {
                // Timeout — kill the child
                let _ = child.kill().await;
                Err(StudioError::Subprocess("timeout".into()))
            }
        }
    }

    /// Send user input to the subprocess stdin.
    pub async fn send_input(&self, text: &str) -> StudioResult<()> {
        // The handle doesn't own stdin directly — it's in the child.
        // We need a different design: stdin is held separately.
        // This will be addressed by the Runner holding a stdin handle.
        // For now, this is a placeholder that returns an error.
        // The real implementation uses the stdin handle stored alongside.
        Err(StudioError::Subprocess(
            "stdin handle not available — use Runner::send_input".into(),
        ))
    }

    /// Collect all events parsed from fd 3 so far.
    pub async fn collect_events(&self) -> Vec<serde_json::Value> {
        self.events.lock().await.clone()
    }

    /// Read captured stdout.
    pub async fn read_stdout(&self) -> String {
        self.stdout.lock().await.clone()
    }

    /// Read captured stderr.
    pub async fn read_stderr(&self) -> String {
        self.stderr.lock().await.clone()
    }

    /// Get the trace directory path.
    pub fn trace_dir(&self) -> &Path {
        &self.trace_dir
    }

    /// Stop (kill) the subprocess.
    pub async fn stop(&self) -> StudioResult<()> {
        if let Some(child) = &self.child {
            // Try SIGTERM first (on Unix)
            #[cfg(unix)]
            {
                use std::os::unix::process::ExitStatusExt;
                if let Some(pid) = child.id() {
                    let _ = nix::sys::signal::kill(
                        nix::unistd::Pid::from_raw(pid as i32),
                        nix::sys::signal::Signal::SIGTERM,
                    );
                    // Give it 2 seconds to exit gracefully
                    match tokio::time::timeout(
                        std::time::Duration::from_secs(2),
                        child.wait(),
                    )
                    .await
                    {
                        Ok(Ok(_)) => return Ok(()),
                        _ => {}
                    }
                }
            }
            // Fallback: SIGKILL
            child.kill().await.map_err(|e| {
                StudioError::Subprocess(format!("kill failed: {e}"))
            })?;
        }
        Ok(())
    }
}

/// Manages user agent subprocess runs.
pub struct Runner {
    /// Active runs: run_id → (RunHandle, stdin_writer)
    runs: Arc<Mutex<std::collections::HashMap<String, RunEntry>>>,
}

struct RunEntry {
    handle: Arc<RunHandle>,
    stdin: Arc<Mutex<Option<tokio::process::ChildStdin>>>,
}

impl Runner {
    pub fn new() -> Self {
        Self {
            runs: Arc::new(Mutex::new(std::collections::HashMap::new())),
        }
    }

    /// Start a new run.
    pub async fn start(&self, config: RunConfig) -> StudioResult<Arc<RunHandle>> {
        let run_id = config.run_id.clone();
        let trace_dir = config.project_dir.join(".studio/runs").join(&run_id);
        std::fs::create_dir_all(&trace_dir)?;

        // Create the fd 3 pipe: we need a pair of fds.
        // On Unix, use socketpair or pipe.
        #[cfg(unix)]
        let (fd3_read, fd3_write) = {
            use std::os::unix::io::FromRawFd;
            let (read_fd, write_fd) = {
                let mut fds = [0i32; 2];
                let ret = unsafe { libc::pipe(fds.as_mut_ptr()) };
                if ret != 0 {
                    return Err(StudioError::Subprocess("pipe() failed".into()));
                }
                (fds[0], fds[1])
            };
            (
                unsafe { std::fs::File::from_raw_fd(read_fd) },
                unsafe { std::fs::File::from_raw_fd(write_fd) },
            )
        };

        #[cfg(not(unix))]
        let (fd3_read, fd3_write) = {
            return Err(StudioError::Subprocess(
                "fd 3 pipe not supported on non-Unix".into(),
            ));
        };

        // Build the command
        let mut cmd = Command::new("python3");
        cmd.arg(&config.main_script)
            .current_dir(&config.project_dir)
            .env("SENZA_STUDIO_RUN_ID", &run_id)
            .env("SENZA_STUDIO_TRACE_DIR", &trace_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Set fd 3 as the write end of the pipe
        // On Unix, we need to pass it as a specific fd.
        // tokio::process::Command doesn't directly support fd allocation,
        // so we use std::process::Command's pre_exec or the std::os::unix::CommandExt.
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // We need fd 3 to be the write end. The std Command will set up
            // stdin (0), stdout (1), stderr (2) as piped. We need to ensure
            // fd 3 is the write end of our pipe.
            // The approach: after fork, before exec, dup2 the write fd to 3.
            // But tokio::process::Command doesn't support pre_exec directly.
            // Instead, we use the std Command and then spawn via tokio.
            // Actually, tokio::process::Command does support pre_exec on Unix.
            let fd3_write_raw = fd3_write.as_raw_fd();
            unsafe {
                cmd.pre_exec(move || {
                    // dup2 the write fd to fd 3
                    if libc::dup2(fd3_write_raw, 3) == -1 {
                        return Err(std::io::Error::last_os_error());
                    }
                    Ok(())
                });
            }
        }

        let mut child = cmd.spawn().map_err(|e| {
            StudioError::Subprocess(format!("failed to spawn python3: {e}"))
        })?;

        // Close the write end in the parent (child has it)
        drop(fd3_write);

        // Take stdin, stdout, stderr
        let stdin = child.stdin.take().ok_or_else(|| {
            StudioError::Subprocess("failed to capture stdin".into())
        })?;
        let stdout = child.stdout.take().ok_or_else(|| {
            StudioError::Subprocess("failed to capture stdout".into())
        })?;
        let stderr = child.stderr.take().ok_or_else(|| {
            StudioError::Subprocess("failed to capture stderr".into())
        })?;

        let events = Arc::new(Mutex::new(Vec::new()));
        let stdout_buf = Arc::new(Mutex::new(String::new()));
        let stderr_buf = Arc::new(Mutex::new(String::new()));

        // Spawn tasks to read stdout, stderr, and fd 3
        let stdout_clone = stdout_buf.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(stdout);
            let mut buf = String::new();
            reader.read_to_string(&mut buf).await.ok();
            *stdout_clone.lock().await = buf;
        });

        let stderr_clone = stderr_buf.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(stderr);
            let mut buf = String::new();
            reader.read_to_string(&mut buf).await.ok();
            *stderr_clone.lock().await = buf;
        });

        // Read fd 3: convert the File to a tokio file
        let fd3_events = events.clone();
        let trace_dir_clone = trace_dir.clone();
        tokio::spawn(async move {
            let mut file = tokio::fs::File::from_std(fd3_read);
            let mut parser = FrameParser::new();
            let mut buf = [0u8; 4096];

            // Also write events to events.jsonl
            let events_file = trace_dir_clone.join("events.jsonl");

            loop {
                match file.read(&mut buf).await {
                    Ok(0) => break, // EOF
                    Ok(n) => {
                        let data = String::from_utf8_lossy(&buf[..n]);
                        let parsed = parser.feed(&data);
                        let mut events_lock = fd3_events.lock().await;
                        for event in &parsed {
                            events_lock.push(event.clone());
                            // Append to events.jsonl
                            let line = serde_json::to_string(event).unwrap_or_default();
                            let _ = tokio::fs::OpenOptions::new()
                                .create(true)
                                .append(true)
                                .open(&events_file)
                                .await
                                .and_then(|mut f| async move {
                                    f.write_all(format!("{line}\n").as_bytes()).await
                                });
                        }
                    }
                    Err(_) => break,
                }
            }
        });

        let handle = Arc::new(RunHandle {
            run_id: run_id.clone(),
            child: Some(child),
            events,
            stdout: stdout_buf,
            stderr: stderr_buf,
            trace_dir,
        });

        // Store the run with stdin handle
        self.runs.lock().await.insert(
            run_id,
            RunEntry {
                handle: handle.clone(),
                stdin: Arc::new(Mutex::new(Some(stdin))),
            },
        );

        Ok(handle)
    }

    /// Send input to a running subprocess's stdin.
    pub async fn send_input(&self, run_id: &str, text: &str) -> StudioResult<()> {
        let runs = self.runs.lock().await;
        let entry = runs
            .get(run_id)
            .ok_or_else(|| StudioError::RunNotFound(run_id.into()))?;
        let mut stdin_guard = entry.stdin.lock().await;
        if let Some(stdin) = stdin_guard.as_mut() {
            stdin
                .write_all(format!("{text}\n").as_bytes())
                .await
                .map_err(|e| StudioError::Subprocess(format!("stdin write failed: {e}")))?;
            stdin
                .flush()
                .await
                .map_err(|e| StudioError::Subprocess(format!("stdin flush failed: {e}")))?;
            Ok(())
        } else {
            Err(StudioError::Subprocess("stdin already closed".into()))
        }
    }

    /// Stop a running subprocess.
    pub async fn stop(&self, run_id: &str) -> StudioResult<()> {
        let runs = self.runs.lock().await;
        let entry = runs
            .get(run_id)
            .ok_or_else(|| StudioError::RunNotFound(run_id.into()))?;
        entry.handle.stop().await
    }

    /// Check if a run is still active.
    pub async fn is_running(&self, run_id: &str) -> bool {
        let runs = self.runs.lock().await;
        if let Some(entry) = runs.get(run_id) {
            if let Some(child) = &entry.handle.child {
                // Try to check if the process is still running
                // On Unix, we can try waitpid with WNOHANG
                // For simplicity, we check if the child's stdin is still open
                return entry.stdin.lock().await.is_some();
            }
        }
        false
    }

    /// Get a run handle.
    pub async fn get_run(&self, run_id: &str) -> Option<Arc<RunHandle>> {
        self.runs
            .lock()
            .await
            .get(run_id)
            .map(|e| e.handle.clone())
    }

    /// Remove a completed run from the active map.
    pub async fn remove_run(&self, run_id: &str) {
        self.runs.lock().await.remove(run_id);
    }
}

impl Default for Runner {
    fn default() -> Self {
        Self::new()
    }
}
```

- [ ] **Step 4: Add libc dependency**

Modify `crates/studio-core/Cargo.toml` to add:

```toml
libc = "0.2"
```

And in the workspace `Cargo.toml` `[workspace.dependencies]`:

```toml
libc = "0.2"
```

Then update `crates/studio-core/Cargo.toml` `[dependencies]`:

```toml
libc = { workspace = true }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cargo test --lib runner`
Expected: PASS (requires Python 3 installed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Runner with fd 3 frame protocol and subprocess management"
```

---

### Task 4: Runner — events.jsonl Reading API

**Files:**
- Modify: `crates/studio-core/src/runner.rs` (add `read_events` method)

**Interfaces:**
- Produces: `Runner::read_events(project_dir, run_id) -> Vec<Value>`

**Design doc reference:** §6 read_events, §6 read_session

- [ ] **Step 1: Write the failing test**

Add to `runner.rs` tests:

```rust
    #[tokio::test]
    async fn test_read_events_from_jsonl() {
        let tmp = tempfile::TempDir::new().unwrap();
        let trace_dir = tmp.path().join(".studio/runs/test-run-7");
        std::fs::create_dir_all(&trace_dir).unwrap();
        std::fs::write(
            trace_dir.join("events.jsonl"),
            r#"{"type":"step_started","step_id":"s1","step_name":"Step 1"}
{"type":"text_delta","text":"hello"}
{"type":"settled"}
"#,
        )
        .unwrap();

        let runner = Runner::new();
        let events = runner
            .read_events(tmp.path(), "test-run-7")
            .await
            .unwrap();
        assert_eq!(events.len(), 3);
    }

    #[test]
    fn test_read_events_sync() {
        let tmp = tempfile::TempDir::new().unwrap();
        let trace_dir = tmp.path().join(".studio/runs/test-run-8");
        std::fs::create_dir_all(&trace_dir).unwrap();
        std::fs::write(
            trace_dir.join("events.jsonl"),
            r#"{"type":"settled"}
"#,
        )
        .unwrap();

        let events = Runner::read_events_sync(tmp.path(), "test-run-8").unwrap();
        assert_eq!(events.len(), 1);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --lib runner::tests::test_read_events`
Expected: FAIL — method not defined

- [ ] **Step 3: Add read_events methods**

Add to `impl Runner`:

```rust
    /// Read events from events.jsonl for a completed (or in-progress) run.
    pub async fn read_events(
        &self,
        project_dir: &Path,
        run_id: &str,
    ) -> StudioResult<Vec<serde_json::Value>> {
        let path = project_dir
            .join(".studio/runs")
            .join(run_id)
            .join("events.jsonl");
        if !path.exists() {
            return Ok(vec![]);
        }
        let content = tokio::fs::read_to_string(&path).await?;
        Ok(crate::events::parse_events_jsonl(&content))
    }

    /// Read events synchronously (for use in non-async contexts).
    pub fn read_events_sync(
        project_dir: &Path,
        run_id: &str,
    ) -> StudioResult<Vec<serde_json::Value>> {
        let path = project_dir
            .join(".studio/runs")
            .join(run_id)
            .join("events.jsonl");
        if !path.exists() {
            return Ok(vec![]);
        }
        let content = std::fs::read_to_string(&path)?;
        Ok(crate::events::parse_events_jsonl(&content))
    }

    /// List all runs for a project.
    pub fn list_runs(project_dir: &Path) -> StudioResult<Vec<String>> {
        let runs_dir = project_dir.join(".studio/runs");
        if !runs_dir.exists() {
            return Ok(vec![]);
        }
        let mut runs = vec![];
        for entry in std::fs::read_dir(&runs_dir)? {
            let entry = entry?;
            if entry.path().is_dir() {
                if let Some(name) = entry.file_name().to_str() {
                    runs.push(name.to_string());
                }
            }
        }
        runs.sort();
        Ok(runs)
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --lib runner`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add events.jsonl reading API to Runner"
```

---

### Task 5: Update lib.rs and Verify

**Files:**
- Modify: `crates/studio-core/src/lib.rs`

- [ ] **Step 1: Update lib.rs**

```rust
//! studio-core — Core business logic for Senza Studio.
//!
//! No web dependencies. Contains:
//! - Spec data structures and validation
//! - Project management (filesystem CRUD)
//! - Meta-agent definitions (Converser + Coding Agent)
//! - Python subprocess runner with fd 3 frame protocol
//! - Built-in example library

pub mod error;
pub mod events;
pub mod examples;
pub mod frame;
pub mod project;
pub mod runner;
pub mod spec;
```

- [ ] **Step 2: Run all tests**

Run: `cargo test`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: update lib.rs with runner/frame/events modules"
```
