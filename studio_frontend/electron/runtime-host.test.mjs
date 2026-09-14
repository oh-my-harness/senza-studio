import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const {
  AgentTeamRuntimeHost,
  AgentTeamRuntimeSupervisor,
  sanitizeProcessOutput,
} = require("./runtime-host.cjs");

async function makeScript(directory, name, contents) {
  const script = path.join(directory, name);
  await fs.promises.writeFile(script, `#!/bin/sh\n${contents}\n`, "utf8");
  await fs.promises.chmod(script, 0o755);
  return script;
}

function scriptForDescriptor(
  descriptor,
  options = {}
) {
  const ignoredTermination = options.ignoreTermination
    ? "trap '' TERM INT"
    : `trap 'rm -f "${descriptor}" "${descriptor}.tmp"; exit 0' TERM INT`;
  return `${ignoredTermination}
printf 'STUDIO_PANEL_DESCRIPTOR=${descriptor}\\n'
while :; do sleep 0.05; done`;
}

function writeDescriptor(
  descriptor,
  schema = "llm-harness.studio.panel-descriptor.v1"
) {
  fs.writeFileSync(
    descriptor,
    JSON.stringify({ schema, url: "http://127.0.0.1:1#token=redacted" }),
    "utf8"
  );
}

function waitForEvents(events, type, count) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 3000;
    const check = () => {
      if (events.filter((event) => event.type === type).length >= count) {
        resolve();
        return;
      }
      if (Date.now() >= deadline) {
        reject(new Error(`Timed out waiting for ${count} ${type} events`));
        return;
      }
      setTimeout(check, 20);
    };
    check();
  });
}

const itUnix = process.platform === "win32" ? it.skip : it;
const runtimeBinary = process.env.SENZA_STUDIO_AGENT_TEAM_BIN
  ? path.resolve(process.env.SENZA_STUDIO_AGENT_TEAM_BIN)
  : path.resolve(
      process.cwd(),
      "../..",
      "llm-harness-runtime",
      "target",
      "debug",
      process.platform === "win32" ? "agent-studio.exe" : "agent-studio"
    );
const realRuntimeIt = fs.existsSync(runtimeBinary) ? itUnix : itUnix.skip;

describe("Agent Team runtime host", () => {
  itUnix("starts from a valid descriptor and removes it on shutdown", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-host-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(descriptor);
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(descriptor)
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
      shutdownGraceMs: 1000,
    });

    expect(await host.start()).toBe(descriptor);
    await host.stop();
    expect(fs.existsSync(descriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("scrubs Studio secrets from the runtime environment", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-env-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(descriptor);
    const marker = path.join(directory, "secret.txt");
    const program = await makeScript(
      directory,
      "runtime.sh",
      `printf '%s\\n' "\${SENZA_STUDIO_API_TOKEN:-missing}" "\${SENZA_STUDIO_API_KEY:-missing}" "\${VITE_SENZA_STUDIO_API_TOKEN:-missing}" > "${marker}"
${scriptForDescriptor(descriptor)}`
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      environment: {
        ...process.env,
        SENZA_STUDIO_API_TOKEN: "studio-secret-token",
        SENZA_STUDIO_API_KEY: "studio-provider-key",
        VITE_SENZA_STUDIO_API_TOKEN: "vite-secret-token",
      },
      readyTimeoutMs: 2000,
    });

    await host.start();
    await host.stop();
    expect(fs.readFileSync(marker, "utf8")).toBe("missing\nmissing\nmissing\n");
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects a descriptor from another path", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-path-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const expectedDescriptor = path.join(dataRoot, "panel.json");
    const reportedDescriptor = path.join(directory, "other.json");
    writeDescriptor(expectedDescriptor);
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(reportedDescriptor)
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
    });

    await expect(host.start()).rejects.toThrow(
      "Agent Team runtime descriptor path is invalid"
    );
    expect(fs.existsSync(reportedDescriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects an unexpected descriptor schema", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-schema-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(descriptor, "unexpected-schema");
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(descriptor)
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
    });

    await expect(host.start()).rejects.toThrow(
      "Agent Team runtime descriptor schema is invalid"
    );
    expect(fs.existsSync(descriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects a symlinked descriptor", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-symlink-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const realDescriptor = path.join(dataRoot, "real-panel.json");
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(realDescriptor);
    fs.symlinkSync(realDescriptor, descriptor);
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(descriptor)
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
    });

    await expect(host.start()).rejects.toThrow(
      "Agent Team runtime descriptor is invalid"
    );
    expect(fs.existsSync(realDescriptor)).toBe(true);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects an oversized descriptor", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-size-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(descriptor);
    fs.appendFileSync(descriptor, " ".repeat(64 * 1024), "utf8");
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(descriptor)
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
    });

    await expect(host.start()).rejects.toThrow(
      "Agent Team runtime descriptor is invalid"
    );
    expect(fs.existsSync(descriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  it("does not spawn a runtime when shutdown starts first", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-stop-race-")
    );
    const dataRoot = path.join(directory, "data");
    const host = new AgentTeamRuntimeHost({
      program: path.join(directory, "runtime.sh"),
      dataRoot,
      readyTimeoutMs: 2000,
    });

    const startPromise = host.start();
    await host.stop();
    await expect(startPromise).rejects.toThrow(
      "Agent Team runtime is stopping"
    );
    expect(fs.existsSync(path.join(directory, "runtime.sh"))).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("force-kills a runtime that ignores SIGTERM", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-kill-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    writeDescriptor(descriptor);
    const program = await makeScript(
      directory,
      "runtime.sh",
      scriptForDescriptor(descriptor, { ignoreTermination: true })
    );
    const host = new AgentTeamRuntimeHost({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
      shutdownGraceMs: 100,
    });

    await host.start();
    const shutdown = await host.stop();
    expect(shutdown.forced).toBe(true);
    expect(fs.existsSync(descriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("restarts an unexpectedly exited runtime", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-runtime-restart-")
    );
    const dataRoot = path.join(directory, "data");
    await fs.promises.mkdir(dataRoot);
    const descriptor = path.join(dataRoot, "panel.json");
    const counter = path.join(directory, "started");
    const program = await makeScript(
      directory,
      "runtime.sh",
      `cat > "${descriptor}" <<'JSON'
{"schema":"llm-harness.studio.panel-descriptor.v1","url":"http://127.0.0.1:1#token=redacted"}
JSON
if [ ! -f "${counter}" ]; then
  touch "${counter}"
  printf 'STUDIO_PANEL_DESCRIPTOR=${descriptor}\\n'
  sleep 0.2
  exit 0
fi
${scriptForDescriptor(descriptor)}`
    );
    const events = [];
    const supervisor = new AgentTeamRuntimeSupervisor({
      program,
      dataRoot,
      readyTimeoutMs: 2000,
      shutdownGraceMs: 500,
      restartDelaysMs: [10],
      onEvent: (event) => events.push(event),
    });

    expect(await supervisor.start()).toBe(descriptor);
    await waitForEvents(events, "ready", 2);
    expect(events.some((event) => event.type === "restarting")).toBe(true);
    await supervisor.stop();
    expect(fs.existsSync(descriptor)).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  realRuntimeIt("starts and stops the real Agent Team runtime", async () => {
    const dataRoot = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-real-runtime-")
    );
    const host = new AgentTeamRuntimeHost({
      program: runtimeBinary,
      dataRoot,
      readyTimeoutMs: 10000,
      shutdownGraceMs: 10000,
      environment: { ...process.env, RUST_LOG: "error" },
    });

    const descriptorPath = await host.start();
    expect(descriptorPath).toBe(path.join(dataRoot, "panel.json"));
    expect(fs.existsSync(descriptorPath)).toBe(true);
    await host.stop();
    expect(fs.existsSync(descriptorPath)).toBe(false);
    await fs.promises.rm(dataRoot, { recursive: true, force: true });
  });

  it("redacts panel URLs, query tokens, and exact secrets", () => {
    const output = sanitizeProcessOutput(
      "url=http://127.0.0.1:1/app#token=abc\nnext?token=abc\nsecret",
      ["secret"]
    );
    expect(output).toBe(
      "url=[redacted panel url]\nnext?token=[redacted]\n[redacted]"
    );
  });
});
