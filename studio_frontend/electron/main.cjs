// studio_frontend/electron/main.cjs
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

let pythonProcess = null;
let mainWindow = null;

function startBackend() {
  // 开发期：从项目根目录启动 Python 后端
  const projectRoot = path.resolve(__dirname, "../../");
  pythonProcess = spawn("python", ["-m", "studio_backend.server"], {
    cwd: projectRoot,
    env: { ...process.env, PYTHONPATH: projectRoot },
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[backend] ${data}`);
  });
  pythonProcess.stderr.on("data", (data) => {
    console.error(`[backend] ${data}`);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // 开发期加载 Vite dev server，生产期加载后端
  const isDev = !app.isPackaged;
  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadURL("http://localhost:7878");
  }
}

app.whenReady().then(() => {
  startBackend();
  // 等后端启动
  setTimeout(createWindow, 2000);

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
});
