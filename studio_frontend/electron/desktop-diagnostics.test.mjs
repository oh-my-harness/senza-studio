import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { DesktopDiagnosticsLog } = require("./desktop-diagnostics.cjs");

const itUnix = process.platform === "win32" ? it.skip : it;
const MAX_TEXT_CHARS = 16 * 1024;

async function makeDirectory() {
  return fs.promises.mkdtemp(
    path.join(os.tmpdir(), "senza-desktop-diagnostics-")
  );
}

async function readLines(file) {
  const contents = await fs.promises.readFile(file, "utf8");
  return contents
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line));
}

describe("Desktop diagnostics log", () => {
  it("writes schema events with sanitized and bounded data", async () => {
    const directory = await makeDirectory();
    const log = new DesktopDiagnosticsLog({
      filePath: path.join(directory, "logs", "desktop.jsonl"),
      sanitizeOutput: (output) => String(output).replace("secret", "[redacted]"),
      processId: 12345,
      applicationVersion: "test-version",
    });

    await log.open();
    log.record("backend", {
      type: "stdout",
      text: "hello secret",
    });
    log.record("backend", {
      type: "stdout",
      text: "second secret",
    });
    log.record("backend", {
      type: "stdout",
      text: "x".repeat(MAX_TEXT_CHARS + 1),
    });
    log.record("backend", {
      type: "stdout",
      lines: Array.from({ length: 100 }, () => "x".repeat(MAX_TEXT_CHARS)),
    });
    await log.flush();
    await log.close();

    const diagnosticsPath = path.join(directory, "logs", "desktop.jsonl");
    const events = await readLines(diagnosticsPath);
    const contents = await fs.promises.readFile(diagnosticsPath, "utf8");
    expect(events).toHaveLength(4);
    expect(events[0]).toMatchObject({
      schema: "llm-harness.studio.desktop-lifecycle.v1",
      process_id: 12345,
      application_version: "test-version",
      source: "backend",
      data: {
        type: "stdout",
        text: "hello [redacted]",
      },
    });
    expect(events[0].id).not.toBe(events[1].id);
    expect(events[0].timestamp_us).toBeLessThanOrEqual(events[1].timestamp_us);
    expect(events[2].data.text).toContain("[truncated 1 chars]");
    expect(events[3].data).toMatchObject({
      type: "diagnostics-event-truncated",
      original_type: "stdout",
    });
    expect(events[3].data.original_bytes).toBeGreaterThan(64 * 1024);
    expect(
      Buffer.byteLength(`${JSON.stringify(events[3])}\n`)
    ).toBeLessThanOrEqual(64 * 1024);
    expect(contents).not.toContain("secret");
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  it("rotates after reaching the size limit", async () => {
    const directory = await makeDirectory();
    const filePath = path.join(directory, "logs", "desktop.jsonl");
    const log = new DesktopDiagnosticsLog({
      filePath,
      maxBytes: 1,
      maxRotatedFiles: 2,
    });

    await log.open();
    log.record("backend", { type: "stdout", text: "first" });
    await log.flush();
    log.record("backend", { type: "stdout", text: "second" });
    await log.flush();
    await log.close();

    const rotated = await readLines(`${filePath}.1`);
    const current = await readLines(filePath);
    expect(rotated[0].data.text).toBe("first");
    expect(current[0].data.text).toBe("second");
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("keeps private Unix permissions", async () => {
    const directory = await makeDirectory();
    const filePath = path.join(directory, "logs", "desktop.jsonl");
    const log = new DesktopDiagnosticsLog({ filePath });

    await log.open();
    await log.close();

    const logMode = (await fs.promises.stat(filePath)).mode & 0o777;
    const directoryMode =
      (await fs.promises.stat(path.dirname(filePath))).mode & 0o777;
    expect(logMode).toBe(0o600);
    expect(directoryMode).toBe(0o700);
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects a symlinked diagnostics directory", async () => {
    const directory = await makeDirectory();
    const target = path.join(directory, "target");
    await fs.promises.mkdir(target);
    await fs.promises.symlink(target, path.join(directory, "logs"));

    const log = new DesktopDiagnosticsLog({
      filePath: path.join(directory, "logs", "desktop.jsonl"),
    });
    await expect(log.open()).rejects.toThrow(
      "Desktop diagnostics directory is invalid"
    );
    await fs.promises.rm(directory, { recursive: true, force: true });
  });

  itUnix("rejects a symlinked active diagnostics file", async () => {
    const directory = await makeDirectory();
    const target = path.join(directory, "target.jsonl");
    await fs.promises.writeFile(target, "", "utf8");
    const logsDirectory = path.join(directory, "logs");
    await fs.promises.mkdir(logsDirectory);
    const filePath = path.join(logsDirectory, "desktop.jsonl");
    await fs.promises.symlink(target, filePath);

    const log = new DesktopDiagnosticsLog({ filePath });
    await expect(log.open()).rejects.toHaveProperty("code", "ELOOP");
    await fs.promises.rm(directory, { recursive: true, force: true });
  });
});
