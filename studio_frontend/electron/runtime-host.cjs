"use strict";

const { spawn } = require("child_process");
const { execFile } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const DESCRIPTOR_PREFIX = "STUDIO_PANEL_DESCRIPTOR=";
const DESCRIPTOR_SCHEMA = "llm-harness.studio.panel-descriptor.v1";
const MAX_DESCRIPTOR_BYTES = 64 * 1024;
const DEFAULT_READY_TIMEOUT_MS = 30000;
const DEFAULT_SHUTDOWN_GRACE_MS = 10000;
const DEFAULT_RESTART_DELAYS_MS = [250, 500, 1000, 2000, 5000];
const SCRUBBED_ENVIRONMENT_KEYS = [
  "OPENAI_API_KEY",
  "OPENAI_API_BASE",
  "OPENAI_MODEL",
  "STUDIO_API_KEY",
  "SENZA_STUDIO_API_KEY",
  "SENZA_STUDIO_API_BASE",
  "SENZA_STUDIO_MODEL",
  "SENZA_STUDIO_HOME",
  "SENZA_STUDIO_ALLOWED_ORIGINS",
  "SENZA_STUDIO_STATIC_DIR",
  "VITE_SENZA_STUDIO_API_TOKEN",
  "STUDIO_DATA_ROOT",
  "STUDIO_PORT",
  "STUDIO_PANEL_DESCRIPTOR",
  "SENZA_STUDIO_API_TOKEN",
  "SENZA_STUDIO_API_TOKEN_FILE",
  "SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR",
];

function sanitizeProcessOutput(output, secrets = []) {
  let text = String(output);
  text = text.replace(
    /https?:\/\/[^\s"'<>]+#token=[^\s"'<>]+/g,
    "[redacted panel url]"
  );
  text = text.replace(/([?&])token=[^\s&"'<>]+/g, "$1token=[redacted]");
  for (const secret of secrets) {
    if (secret) text = text.split(String(secret)).join("[redacted]");
  }
  return text;
}

function runtimeEnvironment(environment) {
  const result = { ...environment };
  for (const key of SCRUBBED_ENVIRONMENT_KEYS) delete result[key];
  return result;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function execFilePromise(file, arguments_) {
  return new Promise((resolve, reject) => {
    execFile(file, arguments_, (error) => {
      if (error && error.code !== "ENOENT") reject(error);
      else resolve();
    });
  });
}

class AgentTeamRuntimeHost {
  constructor({
    program,
    dataRoot,
    readyTimeoutMs = DEFAULT_READY_TIMEOUT_MS,
    shutdownGraceMs = DEFAULT_SHUTDOWN_GRACE_MS,
    environment = process.env,
    useProcessGroup = true,
    onDiagnostic = () => {},
  }) {
    this.program = program;
    this.dataRoot = path.resolve(dataRoot);
    this.readyTimeoutMs = readyTimeoutMs;
    this.shutdownGraceMs = shutdownGraceMs;
    this.environment = environment;
    this.useProcessGroup = useProcessGroup;
    this.onDiagnostic = onDiagnostic;
    this.onUnexpectedExit = null;
    this.process = null;
    this.stdoutInterface = null;
    this.exitPromise = null;
    this.stopPromise = null;
    this.spawnError = null;
    this.stopping = false;
    this.ready = false;
    this.readyAt = 0;
    this.starting = false;
    this.startupExit = null;
  }

  get descriptorPath() {
    return path.join(this.dataRoot, "panel.json");
  }

  async start() {
    if (this.process) throw new Error("Agent Team runtime is already running");
    await fs.promises.mkdir(this.dataRoot, { recursive: true });
    if (this.stopping) {
      throw new Error("Agent Team runtime is stopping");
    }

    this.process = spawn(this.program, [], {
      cwd: path.dirname(this.program),
      env: {
        ...runtimeEnvironment(this.environment),
        STUDIO_DATA_ROOT: this.dataRoot,
        STUDIO_PORT: "0",
      },
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32" && this.useProcessGroup,
    });
    this.exitPromise = new Promise(
      (resolve) => {
        this.resolveExit = resolve;
      }
    );
    this.starting = true;
    this.process.once("error", (error) => {
      this.spawnError = error;
      this.onDiagnostic({
        type: "error",
        message: sanitizeProcessOutput(error.message),
      });
    });
    this.process.once("exit", (code, signal) => {
      const exit = { code, signal };
      const wasReady = this.ready;
      this.ready = false;
      if (this.starting) this.startupExit = exit;
      this.resolveExit(exit);
      this.clearDescriptor()
        .catch(() => {})
        .finally(() => {
          this.onDiagnostic({ type: "exit", exit });
          if (
            !this.starting &&
            wasReady &&
            !this.stopping &&
            this.onUnexpectedExit
          ) {
            this.onUnexpectedExit(exit);
          }
        });
    });
    this.stdoutInterface = readline.createInterface({
      input: this.process.stdout,
    });
    this.process.stderr.on("data", (data) => {
      this.onDiagnostic({
        type: "stderr",
        text: sanitizeProcessOutput(data),
      });
    });

    const startupEvent = await this.waitForReadiness();
    if (startupEvent.type !== "descriptor") {
      await this.stop();
      if (startupEvent.type === "timeout") {
        throw new Error(
          `Agent Team runtime did not become ready within ${Math.round(
            this.readyTimeoutMs / 1000
          )}s`
        );
      }
      if (startupEvent.type === "error") throw startupEvent.error;
      throw new Error(
        `Agent Team runtime exited before readiness: ${formatExit(
          startupEvent.exit
        )}`
      );
    }

    try {
      await this.validateDescriptor(startupEvent.value);
    } catch (error) {
      await this.stop();
      await this.clearDescriptor();
      throw error;
    }

    if (this.startupExit) {
      await this.stop();
      throw new Error(
        `Agent Team runtime exited before readiness: ${formatExit(
          this.startupExit
        )}`
      );
    }
    this.starting = false;
    this.ready = true;
    this.readyAt = Date.now();
    this.onDiagnostic({
      type: "ready",
      descriptorPath: this.descriptorPath,
    });
    return this.descriptorPath;
  }

  async waitForReadiness() {
    let reportDescriptor;
    let reportExit;
    let reportError;
    const handleLine = (line) => {
      const text = line.trimEnd();
      if (text.startsWith(DESCRIPTOR_PREFIX)) {
        reportDescriptor(text.slice(DESCRIPTOR_PREFIX.length));
      } else {
        this.stdoutInterface.once("line", handleLine);
      }
    };
    const eventPromise = new Promise((resolve) => {
      reportDescriptor = (value) => resolve({ type: "descriptor", value });
      reportExit = (exit) => resolve({ type: "exit", exit });
      reportError = (error) => {
        this.spawnError = error;
        resolve({ type: "error", error });
      };
      this.stdoutInterface.once("line", handleLine);
      this.process.once("exit", reportExit);
      this.process.once("error", reportError);
    });
    const timeoutPromise = sleep(this.readyTimeoutMs).then(() => ({
      type: "timeout",
    }));
    const event = await Promise.race([eventPromise, timeoutPromise]);
    this.stdoutInterface.removeAllListeners("line");
    this.process.removeListener("exit", reportExit);
    this.process.removeListener("error", reportError);
    return event;
  }

  async validateDescriptor(reportedPath) {
    const expectedPath = this.descriptorPath;
    const normalizedReportedPath = path.resolve(reportedPath.trim());
    if (normalizedReportedPath !== expectedPath) {
      throw new Error("Agent Team runtime descriptor path is invalid");
    }
    const metadata = await fs.promises.lstat(expectedPath);
    if (!metadata.isFile() || metadata.size > MAX_DESCRIPTOR_BYTES) {
      throw new Error("Agent Team runtime descriptor is invalid");
    }
    const openFlags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0);
    const fileHandle = await fs.promises.open(expectedPath, openFlags);
    let contents;
    try {
      const handleMetadata = await fileHandle.stat();
      if (
        !handleMetadata.isFile() ||
        handleMetadata.size > MAX_DESCRIPTOR_BYTES
      ) {
        throw new Error("Agent Team runtime descriptor is invalid");
      }
      const buffer = Buffer.alloc(handleMetadata.size);
      await fileHandle.read(buffer, 0, handleMetadata.size, 0);
      contents = buffer.toString("utf8");
    } finally {
      await fileHandle.close();
    }
    const descriptor = JSON.parse(contents);
    if (
      typeof descriptor !== "object" ||
      descriptor === null ||
      Array.isArray(descriptor) ||
      descriptor.schema !== DESCRIPTOR_SCHEMA
    ) {
      throw new Error("Agent Team runtime descriptor schema is invalid");
    }
  }

  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    if (!this.process) return { forced: false };
    const childProcess = this.process;
    this.stopPromise = (async () => {
      if (!childProcess.pid && this.spawnError) {
        await this.clearDescriptor();
        return { forced: false, error: this.spawnError };
      }
      if (childProcess.exitCode === null && childProcess.signalCode === null) {
        const forced = await this.terminateProcess(childProcess);
        const exit = await this.exitPromise;
        await this.clearDescriptor();
        return { forced, exit };
      }
      const exit = await this.exitPromise;
      await this.clearDescriptor();
      return { forced: false, exit };
    })();
    return this.stopPromise;
  }

  async terminateProcess(childProcess) {
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        this.forceKill(childProcess)
          .catch(() => {})
          .then(() => resolve(true));
      }, this.shutdownGraceMs);
      childProcess.once("exit", () => {
        clearTimeout(timeout);
        resolve(false);
      });
      this.sendTerminationSignal(childProcess).catch(() => {});
    });
  }

  async sendTerminationSignal(childProcess) {
    if (!childProcess.pid) return;
    if (process.platform === "win32") {
      childProcess.kill();
      return;
    }
    if (!this.useProcessGroup) {
      childProcess.kill("SIGTERM");
      return;
    }
    try {
      process.kill(-childProcess.pid, "SIGTERM");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }

  async forceKill(childProcess) {
    if (!childProcess.pid) return;
    if (process.platform === "win32") {
      await execFilePromise("taskkill", [
        "/PID",
        String(childProcess.pid),
        "/T",
        "/F",
      ]);
      return;
    }
    if (!this.useProcessGroup) {
      childProcess.kill("SIGKILL");
      return;
    }
    try {
      process.kill(-childProcess.pid, "SIGKILL");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
    childProcess.kill("SIGKILL");
  }

  async clearDescriptor() {
    await fs.promises.rm(this.descriptorPath, { force: true });
    await fs.promises.rm(`${this.descriptorPath}.tmp`, { force: true });
  }
}

class AgentTeamRuntimeSupervisor {
  constructor({
    program,
    dataRoot,
    readyTimeoutMs,
    shutdownGraceMs,
    environment = process.env,
    useProcessGroup,
    restartDelaysMs = DEFAULT_RESTART_DELAYS_MS,
    maxRestartAttempts = 5,
    restartResetIntervalMs = 30000,
    onEvent = () => {},
  }) {
    this.program = program;
    this.dataRoot = dataRoot;
    this.readyTimeoutMs = readyTimeoutMs;
    this.shutdownGraceMs = shutdownGraceMs;
    this.environment = environment;
    this.useProcessGroup = useProcessGroup;
    this.restartDelaysMs = restartDelaysMs;
    this.maxRestartAttempts = maxRestartAttempts;
    this.restartResetIntervalMs = restartResetIntervalMs;
    this.onEvent = onEvent;
    this.currentHost = null;
    this.restartTimer = null;
    this.restartAttempt = 0;
    this.started = false;
    this.stopping = false;
    this.descriptorPath = null;
  }

  async start() {
    if (this.started) throw new Error("Agent Team supervisor is already started");
    this.started = true;
    this.stopping = false;
    this.descriptorPath = await this.spawnHost();
    return this.descriptorPath;
  }

  async spawnHost() {
    const host = new AgentTeamRuntimeHost({
      program: this.program,
      dataRoot: this.dataRoot,
      readyTimeoutMs: this.readyTimeoutMs,
      shutdownGraceMs: this.shutdownGraceMs,
      environment: this.environment,
      useProcessGroup: this.useProcessGroup,
      onDiagnostic: (event) => this.emitEvent(event),
    });
    host.onUnexpectedExit = (exit) => this.scheduleRestart(exit);
    this.currentHost = host;
    this.emitEvent({ type: "starting" });
    const descriptorPath = await host.start();
    this.descriptorPath = descriptorPath;
    return descriptorPath;
  }

  scheduleRestart(exit) {
    if (this.stopping || !this.started) return;
    if (
      this.currentHost &&
      Date.now() - this.currentHost.readyAt >= this.restartResetIntervalMs
    ) {
      this.restartAttempt = 0;
    }
    this.currentHost = null;
    this.emitEvent({ type: "exit", exit });
    if (this.restartAttempt >= this.maxRestartAttempts) {
      this.emitEvent({
        type: "failed",
        reason: "Agent Team runtime restart limit reached",
      });
      return;
    }
    const delayIndex = Math.min(this.restartAttempt, this.restartDelaysMs.length - 1);
    const delayMs = this.restartDelaysMs[delayIndex];
    this.restartAttempt += 1;
    this.emitEvent({ type: "restarting", attempt: this.restartAttempt, delayMs });
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      this.spawnHost().catch((error) => {
        this.currentHost = null;
        this.emitEvent({
          type: "failed",
          reason: sanitizeProcessOutput(error.message),
        });
        this.scheduleRestart({ code: null, signal: null });
      });
    }, delayMs);
  }

  async stop() {
    this.stopping = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const currentHost = this.currentHost;
    this.currentHost = null;
    if (!currentHost) return { forced: false };
    const shutdown = await currentHost.stop();
    this.emitEvent({ type: "stopped", forced: shutdown.forced });
    return shutdown;
  }

  emitEvent(event) {
    this.onEvent(event);
  }
}

function formatExit(exit) {
  if (!exit) return "unknown status";
  if (exit.signal) return `signal ${exit.signal}`;
  return `exit code ${exit.code}`;
}

module.exports = {
  AgentTeamRuntimeHost,
  AgentTeamRuntimeSupervisor,
  sanitizeProcessOutput,
};
