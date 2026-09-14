"use strict";

const fs = require("fs");
const crypto = require("crypto");
const path = require("path");

function packagedResourceDirectory(context) {
  if (process.platform === "darwin") {
    return path.join(context.appOutDir, "Contents", "Resources");
  }
  return path.join(context.appOutDir, "resources");
}

function requireRegularFile(filePath, resources) {
  if (fs.lstatSync(filePath).isSymbolicLink()) {
    const resolvedPath = fs.realpathSync(filePath);
    const resourceRoot = fs.realpathSync(resources);
    const relativePath = path.relative(resourceRoot, resolvedPath);
    if (
      !relativePath ||
      relativePath.startsWith("..") ||
      path.isAbsolute(relativePath)
    ) {
      throw new Error(`Packaged resource escapes the resource root: ${filePath}`);
    }
  }
  const stat = fs.statSync(filePath);
  if (!stat.isFile()) {
    throw new Error(`Packaged resource is not a regular file: ${filePath}`);
  }
  return stat;
}

function requireExecutableFile(filePath, resources) {
  requireRegularFile(filePath, resources);
  fs.accessSync(filePath, fs.constants.X_OK);
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function pythonRuntimePlatform() {
  if (process.platform === "win32") return "windows-x86_64";
  if (process.platform === "darwin") {
    return process.arch === "arm64" ? "mac-arm64" : "mac-x86_64";
  }
  if (process.platform === "linux") {
    return process.arch === "arm64" ? "linux-arm64" : "linux-x86_64";
  }
  throw new Error(`Unsupported packaging platform: ${process.platform}`);
}

function findPythonBytecode(root) {
  const pending = [root];
  while (pending.length > 0) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "__pycache__") return entryPath;
        pending.push(entryPath);
      } else if (entry.isFile() && entry.name.endsWith(".pyc")) {
        return entryPath;
      }
    }
  }
  return null;
}

module.exports = function verifyPack(context) {
  const resources = packagedResourceDirectory(context);
  const platform = process.platform;
  const runtimeName = platform === "win32" ? "agent-studio.exe" : "agent-studio";
  const pythonName = platform === "win32" ? "python.exe" : "bin/python";

  requireExecutableFile(path.join(resources, runtimeName), resources);
  requireExecutableFile(path.join(resources, "python", pythonName), resources);
  requireRegularFile(
    path.join(resources, "senza-studio-backend", "studio_backend", "server.py"),
    resources
  );
  requireRegularFile(
    path.join(resources, "senza-studio-backend", "senza-sdk.lock"),
    resources
  );
  requireRegularFile(
    path.join(resources, "studio_frontend", "dist", "index.html"),
    resources
  );
  requireRegularFile(path.join(resources, "python-runtime.json"), resources);
  const pythonBytecode = findPythonBytecode(resources);
  if (pythonBytecode) {
    throw new Error(`Packaged Python bytecode artifact is present: ${pythonBytecode}`);
  }

  const manifestPath = path.join(resources, "desktop-resources.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const sdkMetadataPath = path.join(
    resources,
    "senza-studio-backend",
    `senza_sdk-${manifest.senza_sdk_version}.dist-info`,
    "METADATA"
  );
  requireRegularFile(sdkMetadataPath, resources);
  if (
    manifest.schema !== "llm-harness.studio.desktop-resources.v1" ||
    !/^[0-9a-f]{64}$/.test(manifest.agent_team_sha256) ||
    !/^[0-9a-f]{64}$/.test(manifest.python_archive_sha256) ||
    !/^\d+\.\d+\.\d+/.test(manifest.senza_sdk_version)
  ) {
    throw new Error("Packaged resource manifest is invalid");
  }
  if (sha256File(path.join(resources, runtimeName)) !== manifest.agent_team_sha256) {
    throw new Error("Packaged Agent Team runtime checksum mismatch");
  }
  const runtimeMetadata = JSON.parse(
    fs.readFileSync(path.join(resources, "python-runtime.json"), "utf8")
  );
  const runtimePlatform = runtimeMetadata.platforms[pythonRuntimePlatform()];
  if (
    !runtimePlatform ||
    runtimePlatform.sha256 !== manifest.python_archive_sha256
  ) {
    throw new Error("Packaged Python runtime metadata mismatch");
  }
};
