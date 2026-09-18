// studio_frontend/electron/main.cjs
const { app, BrowserWindow } = require("electron");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");
const { DesktopDiagnosticsLog } = require("./desktop-diagnostics.cjs");
const { DesktopProcessHost } = require("./desktop-process-host.cjs");
const {
  backendUrlFromPort,
  selectBackendPort,
} = require("./backend-port.cjs");
const {
  AgentTeamRuntimeSupervisor,
  sanitizeProcessOutput,
} = require("./runtime-host.cjs");

let backendHost = null;
let viteHost = null;
let runtimeSupervisor = null;
let mainWindow = null;
let backendExit = null;
let desktopDiagnostics = null;
let shuttingDown = false;
let shutdownPromise = null;

const projectRoot = path.resolve(__dirname, "../../");
const frontendRoot = path.resolve(__dirname, "..");
const backendRoot = app.isPackaged
  ? path.join(process.resourcesPath, "senza-studio-backend")
  : projectRoot;
const apiToken =
  process.env.SENZA_STUDIO_API_TOKEN || crypto.randomBytes(32).toString("hex");
let backendPort = null;
let backendUrl = null;
const frontendUrl = "http://localhost:5173";

process.once("SIGTERM", () => {
  if (!shutdownPromise && !shuttingDown) app.quit();
});
process.once("SIGINT", () => {
  if (!shutdownPromise && !shuttingDown) app.quit();
});

function pythonCommand() {
  const configuredPython = process.env.SENZA_STUDIO_PYTHON;
  if (configuredPython) return configuredPython;
  if (app.isPackaged) {
    return path.join(
      process.resourcesPath,
      "python",
      process.platform === "win32" ? "python.exe" : "bin/python"
    );
  }
  const venvPython = path.join(
    backendRoot,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
  return fs.existsSync(venvPython) ? venvPython : "python";
}

function agentTeamBinaryPath(isPackaged) {
  const configuredPath = process.env.SENZA_STUDIO_AGENT_TEAM_BIN;
  if (configuredPath) return configuredPath;
  if (isPackaged) {
    return path.join(
      process.resourcesPath,
      process.platform === "win32" ? "agent-studio.exe" : "agent-studio"
    );
  }
  return path.join(
    projectRoot,
    "..",
    "llm-harness-runtime",
    "target",
    "debug",
    process.platform === "win32" ? "agent-studio.exe" : "agent-studio"
  );
}

function formatExit(code, signal) {
  if (signal) return `signal ${signal}`;
  return `exit code ${code}`;
}

function recordDiagnostics(source, data) {
  if (desktopDiagnostics) desktopDiagnostics.record(source, data);
}

function logRuntimeEvent(event) {
  recordDiagnostics("agent-team", event);
  if (event.type === "stderr") {
    console.error(
      `[agent-team] ${sanitizeProcessOutput(event.text, [apiToken])}`
    );
    return;
  }
  if (event.type === "error") {
    console.error(
      `[agent-team] ${sanitizeProcessOutput(event.message, [apiToken])}`
    );
    return;
  }
  console.log(`[agent-team] ${event.type}`);
}

function logProcessEvent(source, event) {
  recordDiagnostics(source, event);
  if (event.type === "stdout") {
    console.log(`[${source}] ${event.text}`);
  } else if (event.type === "stderr") {
    console.error(`[${source}] ${event.text}`);
  } else if (event.type === "error") {
    console.error(`[${source}] ${event.message}`);
  } else if (event.type === "exit" && !shuttingDown) {
    console.error(
      `[${source}] exited unexpectedly: ${formatExit(
        event.exit.code,
        event.exit.signal
      )}`
    );
    app.quit();
  }
}

async function startDiagnostics() {
  desktopDiagnostics = new DesktopDiagnosticsLog({
    filePath: path.join(app.getPath("userData"), "logs", "desktop.jsonl"),
    sanitizeOutput: (output) => sanitizeProcessOutput(output, [apiToken]),
    applicationVersion: app.getVersion(),
  });
  await desktopDiagnostics.open();
  recordDiagnostics("host", {
    type: "starting",
    platform: process.platform,
    packaged: app.isPackaged,
    electron_version: process.versions.electron,
  });
}

async function closeDiagnostics() {
  if (!desktopDiagnostics) return;
  await desktopDiagnostics.flush();
  await desktopDiagnostics.close();
}

async function startAgentTeamRuntime() {
  runtimeSupervisor = new AgentTeamRuntimeSupervisor({
    program: agentTeamBinaryPath(app.isPackaged),
    dataRoot: path.join(app.getPath("userData"), "agent-team"),
    useProcessGroup: false,
    onEvent: logRuntimeEvent,
  });
  return runtimeSupervisor.start();
}

function startBackend(agentTeamDescriptorPath) {
  const backendEnvironment = { ...process.env };
  delete backendEnvironment.SENZA_STUDIO_API_TOKEN_FILE;
  delete backendEnvironment.SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR;
  backendHost = new DesktopProcessHost({
    name: "backend",
    command: pythonCommand(),
    arguments: ["-m", "studio_backend.server"],
    cwd: backendRoot,
    environment: {
      ...backendEnvironment,
      PYTHONPATH: backendRoot,
      PYTHONNOUSERSITE: "1",
      SENZA_STUDIO_API_TOKEN: apiToken,
      SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR: agentTeamDescriptorPath,
      SENZA_STUDIO_PORT: String(backendPort),
      ...(app.isPackaged
        ? {
            SENZA_STUDIO_ALLOWED_ORIGINS: backendUrl,
            SENZA_STUDIO_STATIC_DIR: path.join(
              process.resourcesPath,
              "studio_frontend",
              "dist"
            ),
          }
        : {}),
    },
    useProcessGroup: false,
    formatOutput: (output) => sanitizeProcessOutput(output, [apiToken]),
    onEvent: (event) => logProcessEvent("backend", event),
  });
  backendHost.start();
  backendExit = backendHost.exitPromise;
}

function startVite() {
  const viteEntry = path.join(
    frontendRoot,
    "node_modules",
    "vite",
    "bin",
    "vite.js"
  );
  viteHost = new DesktopProcessHost({
    name: "vite",
    command: process.execPath,
    arguments: [viteEntry],
    cwd: frontendRoot,
    environment: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      SENZA_STUDIO_PORT: String(backendPort),
    },
    useProcessGroup: false,
    formatOutput: (output) => sanitizeProcessOutput(output, [apiToken]),
    onEvent: (event) => logProcessEvent("vite", event),
  });
  viteHost.start();
}

function waitForHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(url, (response) => {
        response.resume();
        if (
          response.statusCode &&
          response.statusCode >= 200 &&
          response.statusCode < 400
        ) {
          resolve();
        } else {
          retry();
        }
      });
      request.setTimeout(1000, () => request.destroy());
      request.once("error", retry);
    };
    const retry = () => {
      if (Date.now() >= deadline) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(attempt, 250);
    };
    attempt();
  });
}

async function stopProcesses() {
  shuttingDown = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.destroy();
    mainWindow = null;
  }
  recordDiagnostics("host", { type: "shutdown-starting" });
  const targets = [
    {
      name: "backend",
      stop: () => (backendHost ? backendHost.stop() : Promise.resolve()),
    },
    {
      name: "vite",
      stop: () => (viteHost ? viteHost.stop() : Promise.resolve()),
    },
    {
      name: "agent-team",
      stop: () =>
        runtimeSupervisor ? runtimeSupervisor.stop() : Promise.resolve(),
    },
  ];
  const results = await Promise.allSettled(
    targets.map((target) => target.stop())
  );
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      recordDiagnostics("host", {
        type: "shutdown-failed",
        target: targets[index].name,
        error: result.reason,
      });
    }
  });
  const failure = results.find((result) => result.status === "rejected");
  if (failure) throw failure.reason;
  recordDiagnostics("host", { type: "shutdown-stopped" });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  const isDev = !app.isPackaged;
  const targetUrl = isDev ? frontendUrl : backendUrl;
  await mainWindow.webContents.session.cookies.set({
    url: targetUrl,
    name: "senza_studio_api",
    value: apiToken,
    httpOnly: true,
    sameSite: "strict",
  });
  if (isDev) {
    await mainWindow.loadURL(frontendUrl);
    mainWindow.webContents.openDevTools();
  } else {
    await mainWindow.loadURL(backendUrl);
  }
}

app.whenReady().then(async () => {
  try {
    await startDiagnostics();
    backendPort = await selectBackendPort(process.env.SENZA_STUDIO_PORT);
    backendUrl = backendUrlFromPort(backendPort);
    recordDiagnostics("host", {
      type: "backend-port-selected",
      port: backendPort,
    });
    const agentTeamDescriptorPath = await startAgentTeamRuntime();
    startBackend(agentTeamDescriptorPath);
    const backendStartupFailure = backendExit.then((exit) => {
      throw new Error(
        `backend exited before readiness: ${formatExit(exit.code, exit.signal)}`
      );
    });
    backendStartupFailure.catch(() => {});
    await Promise.race([
      waitForHttp(`${backendUrl}/api/health`, 15000),
      backendStartupFailure,
    ]);
    if (!app.isPackaged) {
      startVite();
      const viteStartupFailure = viteHost.exitPromise.then((exit) => {
        throw new Error(
          `vite exited before readiness: ${formatExit(exit.code, exit.signal)}`
        );
      });
      viteStartupFailure.catch(() => {});
      await Promise.race([
        waitForHttp(frontendUrl, 15000),
        viteStartupFailure,
      ]);
    }
    await createWindow();
    recordDiagnostics("host", { type: "started" });
  } catch (error) {
    recordDiagnostics("host", { type: "startup-failed", error });
    console.error(sanitizeProcessOutput(error.message, [apiToken]));
    app.quit();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin" && !shuttingDown && !shutdownPromise) {
    app.quit();
  }
});

app.on("before-quit", (event) => {
  if (shutdownPromise || shuttingDown) return;
  event.preventDefault();
  recordDiagnostics("host", { type: "shutdown-requested" });
  shutdownPromise = stopProcesses()
    .then(async () => {
      await closeDiagnostics();
      app.quit();
    })
    .catch(async (error) => {
      recordDiagnostics("host", { type: "shutdown-error", error });
      console.error(sanitizeProcessOutput(error.message, [apiToken]));
      try {
        await closeDiagnostics();
      } finally {
      app.quit();
      }
    });
});
