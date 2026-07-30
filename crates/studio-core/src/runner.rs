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
use tokio::io::{AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use std::process::Stdio;
use tokio::sync::Mutex;

use crate::error::{StudioError, StudioResult};
use crate::frame::FrameParser;
#[cfg(unix)]
#[allow(unused_imports)]
use std::os::unix::process::CommandExt;

/// Configuration for a run.
#[derive(Debug, Clone)]
pub struct RunConfig {
    pub project_dir: PathBuf,
    pub main_script: PathBuf,
    pub run_id: String,
    pub timeout_secs: u64,
    /// Extra environment variables injected into the subprocess (e.g. API keys).
    pub env_vars: Vec<(String, String)>,
}

/// Handle to a running (or completed) user agent subprocess.
pub struct RunHandle {
    pub run_id: String,
    child: Arc<Mutex<Option<Child>>>,
    events: Arc<Mutex<Vec<serde_json::Value>>>,
    stdout: Arc<Mutex<String>>,
    stderr: Arc<Mutex<String>>,
    trace_dir: PathBuf,
}

impl RunHandle {
    /// Wait for the subprocess to complete (with timeout).
    pub async fn wait(&self) -> StudioResult<std::process::ExitStatus> {
        let mut child_guard = self.child.lock().await;
        let child = child_guard
            .as_mut()
            .ok_or_else(|| StudioError::Subprocess("process already consumed".into()))?;

        let timeout = std::time::Duration::from_secs(300);

        match tokio::time::timeout(timeout, child.wait()).await {
            Ok(Ok(status)) => {
                // Give the stdout/stderr reader tasks time to finish flushing
                // after the child exits — they read until EOF, which arrives
                // when the process closes, but the task may not have run yet.
                tokio::task::yield_now().await;
                tokio::task::yield_now().await;
                Ok(status)
            }
            Ok(Err(e)) => Err(StudioError::Subprocess(format!("wait error: {e}"))),
            Err(_) => {
                let _ = child.kill().await;
                Err(StudioError::Subprocess("timeout".into()))
            }
        }
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
        let mut child_guard = self.child.lock().await;
        if let Some(child) = child_guard.as_mut() {
            #[cfg(unix)]
            {
                if let Some(pid) = child.id() {
                    let _ = nix::sys::signal::kill(
                        nix::unistd::Pid::from_raw(pid as i32),
                        nix::sys::signal::Signal::SIGTERM,
                    );
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
            child
                .kill()
                .await
                .map_err(|e| StudioError::Subprocess(format!("kill failed: {e}")))?;
        }
        Ok(())
    }
}

struct RunEntry {
    handle: Arc<RunHandle>,
    stdin: Arc<Mutex<Option<tokio::process::ChildStdin>>>,
}

/// Manages user agent subprocess runs.
pub struct Runner {
    runs: Arc<Mutex<std::collections::HashMap<String, RunEntry>>>,
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

        #[cfg(unix)]
        {
            use std::os::unix::io::FromRawFd;

            // Create pipe for fd 3
            let mut fds = [0i32; 2];
            let ret = unsafe { libc::pipe(fds.as_mut_ptr()) };
            if ret != 0 {
                return Err(StudioError::Subprocess("pipe() failed".into()));
            }
            let fd3_read_fd = fds[0];
            let fd3_write_fd = fds[1];
            let mut cmd = Command::new("python3");
            cmd.arg(&config.main_script)
                .current_dir(&config.project_dir)
                .env("SENZA_STUDIO_RUN_ID", &run_id)
                .env("SENZA_STUDIO_TRACE_DIR", &trace_dir)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            for (key, value) in &config.env_vars {
                cmd.env(key, value);
            }
            // Set fd 3 as the write end of the pipe using pre_exec
            unsafe {
                cmd.pre_exec(move || {
                    if libc::dup2(fd3_write_fd, 3) == -1 {
                        return Err(std::io::Error::last_os_error());
                    }
                    libc::close(fd3_write_fd);
                    libc::close(fd3_read_fd);
                    Ok(())
                });
            }

            let mut child = cmd
                .spawn()
                .map_err(|e| StudioError::Subprocess(format!("failed to spawn python3: {e}")))?;

            // Close write end in parent (child has it as fd 3)
            unsafe {
                libc::close(fd3_write_fd);
            }

            // Convert read end to a tokio file
            let fd3_read = unsafe { std::fs::File::from_raw_fd(fd3_read_fd) };

            let stdin = child
                .stdin
                .take()
                .ok_or_else(|| StudioError::Subprocess("failed to capture stdin".into()))?;
            let stdout = child
                .stdout
                .take()
                .ok_or_else(|| StudioError::Subprocess("failed to capture stdout".into()))?;
            let stderr = child
                .stderr
                .take()
                .ok_or_else(|| StudioError::Subprocess("failed to capture stderr".into()))?;

            let events = Arc::new(Mutex::new(Vec::new()));
            let stdout_buf = Arc::new(Mutex::new(String::new()));
            let stderr_buf = Arc::new(Mutex::new(String::new()));

            // Spawn stdout reader
            let stdout_clone = stdout_buf.clone();
            tokio::spawn(async move {
                let mut reader = BufReader::new(stdout);
                let mut buf = String::new();
                reader.read_to_string(&mut buf).await.ok();
                *stdout_clone.lock().await = buf;
            });

            // Spawn stderr reader
            let stderr_clone = stderr_buf.clone();
            tokio::spawn(async move {
                let mut reader = BufReader::new(stderr);
                let mut buf = String::new();
                reader.read_to_string(&mut buf).await.ok();
                *stderr_clone.lock().await = buf;
            });

            // Spawn fd 3 reader
            let fd3_events = events.clone();
            let trace_dir_clone = trace_dir.clone();
            tokio::spawn(async move {
                let mut file = tokio::fs::File::from_std(fd3_read);
                let mut parser = FrameParser::new();
                let mut buf = [0u8; 4096];

                let events_file = trace_dir_clone.join("events.jsonl");

                loop {
                    match file.read(&mut buf).await {
                        Ok(0) => break,
                        Ok(n) => {
                            let data = String::from_utf8_lossy(&buf[..n]);
                            let parsed = parser.feed(&data);
                            let mut events_lock = fd3_events.lock().await;
                            for event in &parsed {
                                events_lock.push(event.clone());
                                let line =
                                    serde_json::to_string(event).unwrap_or_default();
                                if let Ok(mut f) = tokio::fs::OpenOptions::new()
                                    .create(true)
                                    .append(true)
                                    .open(&events_file)
                                    .await
                                {
                                    let _ = f
                                        .write_all(format!("{line}\n").as_bytes())
                                        .await;
                                }
                            }
                        }
                        Err(_) => break,
                    }
                }
            });

            let handle = Arc::new(RunHandle {
                run_id: run_id.clone(),
                child: Arc::new(Mutex::new(Some(child))),
                events,
                stdout: stdout_buf,
                stderr: stderr_buf,
                trace_dir,
            });

            self.runs.lock().await.insert(
                run_id,
                RunEntry {
                    handle: handle.clone(),
                    stdin: Arc::new(Mutex::new(Some(stdin))),
                },
            );

            Ok(handle)
        }

        #[cfg(not(unix))]
        {
            Err(StudioError::Subprocess(
                "fd 3 pipe not supported on non-Unix".into(),
            ))
        }
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

    /// Get a run handle.
    pub async fn get_run(&self, run_id: &str) -> Option<Arc<RunHandle>> {
        self.runs
            .lock()
            .await
            .get(run_id)
            .map(|e| e.handle.clone())
    }

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

    /// Read events synchronously.
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

#[cfg(test)]
mod tests {
    use super::*;

    fn make_test_script(dir: &std::path::Path, content: &str) -> std::path::PathBuf {
        let script = dir.join("main.py");
        std::fs::write(&script, content).unwrap();
        script
    }

    #[tokio::test]
    async fn test_run_completes_and_emits_event() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(
            tmp.path(),
            r#"
import os, sys, json
try:
    fd3 = os.fdopen(3, "w")
    event = {"type": "settled"}
    line = json.dumps(event)
    fd3.write(f"{len(line)}\n{line}\n")
    fd3.flush()
    fd3.close()
except OSError:
    pass
print("hello from agent")
"#,
        );

        let runner = Runner::new();
        let config = RunConfig { project_dir: tmp.path().to_path_buf(), main_script: script, run_id: "test-run-1".into(), timeout_secs: 10, env_vars: vec![] };

        let handle = runner.start(config).await.unwrap();
        let exit_status = handle.wait().await.unwrap();
        assert!(exit_status.success());

        let events = handle.collect_events().await;
        assert!(events
            .iter()
            .any(|e| e.get("type").and_then(|t| t.as_str()) == Some("settled")));
    }

    #[tokio::test]
    async fn test_stdout_captured() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(
            tmp.path(),
            r#"
import os, json
try:
    fd3 = os.fdopen(3, "w")
    event = {"type": "settled"}
    line = json.dumps(event)
    fd3.write(f"{len(line)}\n{line}\n")
    fd3.flush()
    fd3.close()
except OSError:
    pass
print("hello from agent")
"#,
        );

        let runner = Runner::new();
        let config = RunConfig { project_dir: tmp.path().to_path_buf(), main_script: script, run_id: "test-run-2".into(), timeout_secs: 10, env_vars: vec![] };

        let handle = runner.start(config).await.unwrap();
        handle.wait().await.unwrap();

        let stdout = handle.read_stdout().await;
        assert!(stdout.contains("hello from agent"));
    }

    #[tokio::test]
    async fn test_send_input_to_stdin() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(
            tmp.path(),
            r#"
line = input()
print(f"echo: {line}")
"#,
        );

        let runner = Runner::new();
        let config = RunConfig { project_dir: tmp.path().to_path_buf(), main_script: script, run_id: "test-run-3".into(), timeout_secs: 10, env_vars: vec![] };

        let handle = runner.start(config).await.unwrap();
        runner.send_input("test-run-3", "hello stdin").await.unwrap();
        let exit = handle.wait().await.unwrap();
        assert!(exit.success());

        let stdout = handle.read_stdout().await;
        assert!(stdout.contains("echo: hello stdin"));
    }

    #[tokio::test]
    async fn test_stop_kills_process() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(
            tmp.path(),
            r#"
import time
while True:
    time.sleep(1)
"#,
        );

        let runner = Runner::new();
        let config = RunConfig { project_dir: tmp.path().to_path_buf(), main_script: script, run_id: "test-run-4".into(), timeout_secs: 30, env_vars: vec![] };

        let handle = runner.start(config).await.unwrap();
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        handle.stop().await.unwrap();
        let exit = handle.wait().await.unwrap();
        assert!(!exit.success());
    }

    #[tokio::test]
    async fn test_trace_dir_env_var_set() {
        let tmp = tempfile::TempDir::new().unwrap();
        let script = make_test_script(
            tmp.path(),
            r#"
import os
assert os.environ.get("SENZA_STUDIO_RUN_ID") == "test-run-6", f"run_id={os.environ.get('SENZA_STUDIO_RUN_ID')}"
assert os.environ.get("SENZA_STUDIO_TRACE_DIR") is not None, "trace_dir not set"
print("env OK")
"#,
        );

        let runner = Runner::new();
        let config = RunConfig { project_dir: tmp.path().to_path_buf(), main_script: script, run_id: "test-run-6".into(), timeout_secs: 10, env_vars: vec![] };

        let handle = runner.start(config).await.unwrap();
        let exit = handle.wait().await.unwrap();
        assert!(exit.success(), "stdout: {}", handle.read_stdout().await);
    }

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
        std::fs::write(trace_dir.join("events.jsonl"), r#"{"type":"settled"}
"#).unwrap();

        let events = Runner::read_events_sync(tmp.path(), "test-run-8").unwrap();
        assert_eq!(events.len(), 1);
    }
}
