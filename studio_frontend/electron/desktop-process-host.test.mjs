import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { DesktopProcessHost } = require("./desktop-process-host.cjs");

const itUnix = process.platform === "win32" ? it.skip : it;

async function makeScript(directory, contents) {
  const script = path.join(directory, "process.sh");
  await fs.promises.writeFile(script, `#!/bin/sh\n${contents}\n`, "utf8");
  await fs.promises.chmod(script, 0o755);
  return script;
}

describe("Desktop process host", () => {
  itUnix("force-kills a process that ignores SIGTERM", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-desktop-process-")
    );
    const host = new DesktopProcessHost({
      name: "test-process",
      command: process.execPath,
      arguments: [
        "-e",
        "process.on('SIGTERM', () => {}); process.stdout.write('ready'); setInterval(() => {}, 100);",
      ],
      cwd: directory,
      environment: process.env,
      shutdownGraceMs: 100,
    });

    const childProcess = await host.start();
    await new Promise((resolve) => {
      childProcess.stdout.once("data", resolve);
    });
    const shutdown = await host.stop();
    expect(shutdown.forced).toBe(true);
    expect(host.process.exitCode !== null || host.process.signalCode !== null)
      .toBe(true);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  it("does not start a process after shutdown", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-desktop-stop-race-")
    );
    const host = new DesktopProcessHost({
      name: "test-process",
      command: path.join(directory, "process.sh"),
      arguments: [],
      cwd: directory,
      environment: process.env,
    });

    await host.stop();
    await expect(host.start()).rejects.toThrow("test-process is stopping");
    expect(fs.existsSync(path.join(directory, "process.sh"))).toBe(false);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  it("reports spawn errors through the startup exit promise", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-desktop-spawn-error-")
    );
    const host = new DesktopProcessHost({
      name: "test-process",
      command: path.join(directory, "missing-command"),
      arguments: [],
      cwd: directory,
      environment: process.env,
    });

    await host.start();
    await expect(host.exitPromise).rejects.toHaveProperty("code", "ENOENT");
    const shutdown = await host.stop();
    expect(shutdown.forced).toBe(false);
    expect(shutdown.error).toHaveProperty("code", "ENOENT");
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  it("reports sanitized process output", async () => {
    const directory = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), "senza-desktop-output-")
    );
    const program = await makeScript(directory, "printf 'secret\\n'");
    const events = [];
    const host = new DesktopProcessHost({
      name: "test-process",
      command: program,
      arguments: [],
      cwd: directory,
      environment: process.env,
      formatOutput: (output) => String(output).replace("secret", "[redacted]"),
      onEvent: (event) => events.push(event),
    });

    await host.start();
    await host.exitPromise;
    await host.stop();
    expect(events).toContainEqual({
      type: "stdout",
      text: "[redacted]\n",
    });
    await fs.promises.rm(directory, { recursive: true, force: true });
  });
});
