"use strict";

const { spawn, execFile } = require("child_process");

const DEFAULT_SHUTDOWN_GRACE_MS = 10000;

function execFilePromise(file, arguments_) {
  return new Promise((resolve, reject) => {
    execFile(file, arguments_, (error) => {
      if (error && error.code !== "ENOENT") reject(error);
      else resolve();
    });
  });
}

class DesktopProcessHost {
  constructor({
    name,
    command,
    arguments: processArguments = [],
    cwd,
    environment,
    shutdownGraceMs = DEFAULT_SHUTDOWN_GRACE_MS,
    onEvent = () => {},
    formatOutput = (output) => String(output),
  }) {
    this.name = name;
    this.command = command;
    this.arguments = processArguments;
    this.cwd = cwd;
    this.environment = environment;
    this.shutdownGraceMs = shutdownGraceMs;
    this.onEvent = onEvent;
    this.formatOutput = formatOutput;
    this.process = null;
    this.exitPromise = null;
    this.stopPromise = null;
    this.spawnError = null;
    this.stopping = false;
  }

  async start() {
    if (this.process) throw new Error(`${this.name} is already running`);
    if (this.stopping) throw new Error(`${this.name} is stopping`);

    this.process = spawn(this.command, this.arguments, {
      cwd: this.cwd,
      env: this.environment,
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
    });
    this.exitPromise = new Promise((resolve, reject) => {
      this.resolveExit = resolve;
      this.rejectExit = reject;
    });
    this.process.once("error", (error) => {
      this.spawnError = error;
      this.rejectExit(error);
      this.onEvent({
        type: "error",
        message: this.formatOutput(error.message),
      });
    });
    this.process.once("exit", (code, signal) => {
      const exit = { code, signal };
      this.resolveExit(exit);
      this.onEvent({ type: "exit", exit });
    });
    this.process.stdout.on("data", (data) => {
      this.onEvent({
        type: "stdout",
        text: this.formatOutput(data),
      });
    });
    this.process.stderr.on("data", (data) => {
      this.onEvent({
        type: "stderr",
        text: this.formatOutput(data),
      });
    });
    return this.process;
  }

  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    if (!this.process) return { forced: false };

    const childProcess = this.process;
    this.stopPromise = (async () => {
      if (!childProcess.pid) {
        try {
          const exit = await this.exitPromise;
          return { forced: false, exit };
        } catch (error) {
          return { forced: false, error };
        }
      }
      if (
        childProcess.exitCode !== null ||
        childProcess.signalCode !== null
      ) {
        const exit = await this.exitPromise;
        return { forced: false, exit };
      }
      const forced = await this.terminateProcess(childProcess);
      const exit = await this.exitPromise;
      return { forced, exit };
    })();
    const shutdown = await this.stopPromise;
    this.onEvent({ type: "stopped", ...shutdown });
    return shutdown;
  }

  async terminateProcess(childProcess) {
    if (
      childProcess.exitCode !== null ||
      childProcess.signalCode !== null
    ) {
      return false;
    }
    return new Promise((resolve, reject) => {
      let forceKillStarted = false;
      const timeout = setTimeout(() => {
        forceKillStarted = true;
        this.forceKill(childProcess)
          .then(() => resolve(true), reject);
      }, this.shutdownGraceMs);
      childProcess.once("exit", () => {
        clearTimeout(timeout);
        if (!forceKillStarted) resolve(false);
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
    try {
      process.kill(-childProcess.pid, "SIGKILL");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
    childProcess.kill("SIGKILL");
  }
}

module.exports = {
  DesktopProcessHost,
};
