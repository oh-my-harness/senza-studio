"use strict";

const fs = require("fs");
const crypto = require("crypto");
const path = require("path");

function sha256File(filePath) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(filePath))
    .digest("hex");
}

function sha256Tree(root) {
  const files = [];
  const visit = (directory, prefix) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) {
        throw new Error(`Resource bundle contains a symbolic link: ${entry.name}`);
      }
      const entryPath = path.join(directory, entry.name);
      const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        visit(entryPath, relativePath);
      } else if (entry.isFile()) {
        files.push({ entryPath, relativePath });
      }
    }
  };
  visit(root, "");
  files.sort((left, right) =>
    Buffer.compare(
      Buffer.from(left.relativePath, "utf8"),
      Buffer.from(right.relativePath, "utf8")
    )
  );

  const digest = crypto.createHash("sha256");
  for (const file of files) {
    const contents = fs.readFileSync(file.entryPath);
    digest.update(`${file.relativePath}\0${contents.length}\0`, "utf8");
    digest.update(contents);
    digest.update("\0", "utf8");
  }
  return digest.digest("hex");
}

function buildManifest(
  resourceDir,
  pythonArchiveSha256,
  senzaSdkVersion,
  agentTeamSource
) {
  const isWindows = process.platform === "win32";
  const runtimeName = isWindows ? "agent-studio.exe" : "agent-studio";
  const pythonName = isWindows
    ? path.join("python", "python.exe")
    : path.join("python", "bin", "python");
  const backendEntrypoint = path.join(
    "senza-studio-backend",
    "studio_backend",
    "server.py"
  );
  const frontendBundle = path.join("studio_frontend", "dist");

  const manifest = {
    schema: "llm-harness.studio.desktop-resources.v1",
    agent_team_sha256: sha256File(path.join(resourceDir, runtimeName)),
    agent_team_source_sha256: sha256File(
      agentTeamSource || path.join(resourceDir, runtimeName)
    ),
    python_archive_sha256: pythonArchiveSha256,
    senza_sdk_version: senzaSdkVersion,
    python_executable_sha256: sha256File(path.join(resourceDir, pythonName)),
    backend_entrypoint_sha256: sha256File(
      path.join(resourceDir, backendEntrypoint)
    ),
    frontend_bundle_sha256: sha256Tree(path.join(resourceDir, frontendBundle)),
  };
  return manifest;
}

function updateManifestAfterSigning(resourceDir) {
  const manifestPath = path.join(resourceDir, "desktop-resources.json");
  const current = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const sourceChecksum = current.agent_team_source_sha256;
  if (!/^[0-9a-f]{64}$/.test(sourceChecksum || "")) {
    throw new Error("Packaged Agent Team source checksum is invalid");
  }
  const updated = buildManifest(
    resourceDir,
    current.python_archive_sha256,
    current.senza_sdk_version
  );
  updated.agent_team_source_sha256 = sourceChecksum;
  fs.writeFileSync(
    manifestPath,
    `${JSON.stringify(updated, null, 2)}\n`,
    "utf8"
  );
  return updated;
}

if (require.main === module) {
  const [
    resourceDir,
    pythonArchiveSha256,
    senzaSdkVersion,
    agentTeamSource,
  ] = process.argv.slice(2);
  if (!resourceDir || !pythonArchiveSha256 || !senzaSdkVersion || !agentTeamSource) {
    throw new Error(
      "Usage: resource-manifest.cjs <resource-dir> <python-archive-sha256> <senza-sdk-version> <agent-team-source>"
    );
  }
  fs.writeFileSync(
    path.join(resourceDir, "desktop-resources.json"),
    `${JSON.stringify(buildManifest(resourceDir, pythonArchiveSha256, senzaSdkVersion, agentTeamSource), null, 2)}\n`,
    "utf8"
  );
}

module.exports = {
  buildManifest,
  sha256File,
  sha256Tree,
  updateManifestAfterSigning,
};
