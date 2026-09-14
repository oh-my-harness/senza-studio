import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, writeFile, chmod, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "vitest";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const verifyPack = require("./verify-pack.cjs");

async function makePackagedApp(manifest) {
  const root = await mkdtemp(path.join(tmpdir(), "senza-verify-pack-"));
  const resources = path.join(root, "resources");
  const backend = path.join(resources, "senza-studio-backend", "studio_backend");
  const backendRoot = path.join(resources, "senza-studio-backend");
  const pythonBin = path.join(resources, "python", "bin");
  const staticRoot = path.join(resources, "studio_frontend", "dist");
  await mkdir(backend, { recursive: true });
  await mkdir(pythonBin, { recursive: true });
  await mkdir(staticRoot, { recursive: true });
  await writeFile(path.join(backend, "server.py"), "");
  await writeFile(path.join(resources, "senza-studio-backend", "senza-sdk.lock"), "");
  await writeFile(path.join(staticRoot, "index.html"), "");
  const agentRuntime = "agent-team-runtime";
  const agentRuntimeSha256 = createHash("sha256")
    .update(agentRuntime)
    .digest("hex");
  await writeFile(path.join(resources, "agent-studio"), agentRuntime);
  await writeFile(path.join(pythonBin, "python"), "");
  await chmod(path.join(resources, "agent-studio"), 0o755);
  await chmod(path.join(pythonBin, "python"), 0o755);
  await writeFile(
    path.join(resources, "desktop-resources.json"),
    JSON.stringify({ ...manifest, agent_team_sha256: agentRuntimeSha256 })
  );
  await writeFile(
    path.join(resources, "python-runtime.json"),
    JSON.stringify({
      platforms: {
        [process.platform === "win32"
          ? "windows-x86_64"
          : process.platform === "darwin"
            ? process.arch === "arm64"
              ? "mac-arm64"
              : "mac-x86_64"
            : process.arch === "arm64"
              ? "linux-arm64"
              : "linux-x86_64"]: { sha256: manifest.python_archive_sha256 },
      },
    })
  );
  const sdkMetadata = path.join(
    backendRoot,
    `senza_sdk-${manifest.senza_sdk_version}.dist-info`
  );
  await mkdir(sdkMetadata, { recursive: true });
  await writeFile(path.join(sdkMetadata, "METADATA"), "");
  return { appOutDir: root, resources };
}

test("accepts a complete packaged resource layout", async () => {
  const context = await makePackagedApp({
    schema: "llm-harness.studio.desktop-resources.v1",
    agent_team_sha256: "a".repeat(64),
    python_archive_sha256: "b".repeat(64),
    senza_sdk_version: "1.3.0",
  });

  assert.doesNotThrow(() => verifyPack(context));
});

test("rejects an invalid resource manifest", async () => {
  const context = await makePackagedApp({
    schema: "invalid-schema",
    agent_team_sha256: "not-a-hash",
    python_archive_sha256: "not-a-hash",
    senza_sdk_version: "not-a-version",
  });

  assert.throws(() => verifyPack(context), /manifest is invalid/u);
});

test("rejects packaged Python bytecode artifacts", async () => {
  const context = await makePackagedApp({
    schema: "llm-harness.studio.desktop-resources.v1",
    agent_team_sha256: "a".repeat(64),
    python_archive_sha256: "b".repeat(64),
    senza_sdk_version: "1.3.0",
  });
  const bytecodeDirectory = path.join(context.resources, "python", "__pycache__");
  await mkdir(bytecodeDirectory, { recursive: true });
  await writeFile(path.join(bytecodeDirectory, "runtime.pyc"), "");

  assert.throws(() => verifyPack(context), /bytecode artifact/u);
});
