// studio_frontend/electron/main.cjs
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");

let pythonProcess = null;
let viteProcess = null;
let mainWindow = null;
let backendExit = null;

const projectRoot = path.resolve(__dirname, "../../");
const frontendRoot = path.resolve(__dirname, "..");
const apiToken =
  process.env.SENZA_STUDIO_API_TOKEN || crypto.randomBytes(32).toString("hex");
const backendUrl = "http://127.0.0.1:7878";
const frontendUrl = "http://localhost:5173";

function pythonCommand() {
  const venvPython = path.join(
    projectRoot,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
  return fs.existsSync(venvPython) ? venvPython : "python";
}

function startBackend() {
  const backendEnv = { ...process.env };
  delete backendEnv.SENZA_STUDIO_API_TOKEN_FILE;
  pythonProcess = spawn(pythonCommand(), ["-m", "studio_backend.server"], {
    cwd: projectRoot,
    env: {
      ...backendEnv,
      PYTHONPATH: projectRoot,
      SENZA_STUDIO_API_TOKEN: apiToken,
    },
  });
  backendExit = new Promise((resolve, reject) => {
    pythonProcess.once("exit", reject);
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[backend] ${data}`);
  });
  pythonProcess.stderr.on("data", (data) => {
    console.error(`[backend] ${data}`);
  });
}

function startVite() {
  const viteEntry = path.join(
    frontendRoot,
    "node_modules",
    "vite",
    "bin",
    "vite.js"
  );
  viteProcess = spawn(process.execPath, [viteEntry], {
    cwd: frontendRoot,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
  });
  viteProcess.stdout.on("data", (data) => {
    console.log(`[vite] ${data}`);
  });
  viteProcess.stderr.on("data", (data) => {
    console.error(`[vite] ${data}`);
  });
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
    startBackend();
    await Promise.race([
      waitForHttp(`${backendUrl}/api/health`, 15000),
      backendExit,
    ]);
    if (!app.isPackaged) {
      startVite();
      await waitForHttp(frontendUrl, 15000);
    }
    await createWindow();
  } catch (error) {
    console.error(error);
    app.quit();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (pythonProcess) {
    pythonProcess.kill();
  }
  if (viteProcess) {
    viteProcess.kill();
  }
});
