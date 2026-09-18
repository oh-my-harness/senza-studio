"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DIAGNOSTICS_SCHEMA = "llm-harness.studio.desktop-lifecycle.v1";
const DEFAULT_MAX_BYTES = 1024 * 1024;
const DEFAULT_MAX_ROTATED_FILES = 10;
const MAX_TEXT_CHARS = 16 * 1024;
const MAX_EVENT_BYTES = 64 * 1024;
const MAX_ARRAY_ITEMS = 64;
const MAX_OBJECT_PROPERTIES = 64;
const MAX_DEPTH = 4;

function isPlainObject(value) {
  if (value === null || typeof value !== "object") return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

class DesktopDiagnosticsLog {
  constructor({
    filePath,
    maxBytes = DEFAULT_MAX_BYTES,
    maxRotatedFiles = DEFAULT_MAX_ROTATED_FILES,
    sanitizeOutput = (output) => String(output),
    processId = process.pid,
    applicationVersion = "",
  }) {
    if (!filePath) throw new Error("Desktop diagnostics file path is required");
    if (!Number.isFinite(maxBytes) || maxBytes <= 0) {
      throw new Error("Desktop diagnostics max bytes must be positive");
    }
    if (!Number.isInteger(maxRotatedFiles) || maxRotatedFiles < 1) {
      throw new Error("Desktop diagnostics rotation count must be positive");
    }

    this.filePath = path.resolve(filePath);
    this.maxBytes = maxBytes;
    this.maxRotatedFiles = maxRotatedFiles;
    this.sanitizeOutput = sanitizeOutput;
    this.processId = processId;
    this.applicationVersion = applicationVersion;
    this.fileHandle = null;
    this.writeQueue = Promise.resolve();
    this.closed = false;
    this.writeFailed = false;
  }

  async open() {
    if (this.fileHandle) {
      throw new Error("Desktop diagnostics log is already open");
    }
    if (this.closed) {
      throw new Error("Desktop diagnostics log is closed");
    }

    await this.ensurePrivateDirectory(path.dirname(this.filePath));
    this.fileHandle = await this.openLogFile();
  }

  record(source, data) {
    if (this.closed || this.writeFailed) return;
    let event;
    try {
      event = this.makeEvent(source, data);
    } catch (error) {
      this.writeFailed = true;
      console.error(`[diagnostics] ${this.sanitizeOutput(error.message)}`);
      return;
    }
    this.writeQueue = this.writeQueue
      .then(() => this.write(event))
      .catch((error) => {
        this.writeFailed = true;
        console.error(
          `[diagnostics] ${this.sanitizeOutput(error.message)}`
        );
      });
  }

  async flush() {
    await this.writeQueue;
  }

  async close() {
    if (this.closed) return;
    await this.flush();
    if (this.fileHandle) {
      await this.fileHandle.close();
      this.fileHandle = null;
    }
    this.closed = true;
  }

  makeEvent(source, data) {
    return {
      schema: DIAGNOSTICS_SCHEMA,
      id: crypto.randomUUID(),
      timestamp_us: this.timestampMicroseconds(),
      process_id: this.processId,
      application_version: this.normalizeString(this.applicationVersion, 128),
      source: this.normalizeString(source, 128),
      data: this.normalizeValue(data, 0),
    };
  }

  timestampMicroseconds() {
    return Math.round((performance.timeOrigin + performance.now()) * 1000);
  }

  normalizeValue(value, depth) {
    if (depth > MAX_DEPTH) return "[truncated]";
    if (value === null) return null;
    if (typeof value === "boolean") return value;
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : String(value);
    }
    if (typeof value === "string") {
      return this.normalizeString(value, MAX_TEXT_CHARS);
    }
    if (Array.isArray(value)) {
      const result = value
        .slice(0, MAX_ARRAY_ITEMS)
        .map((item) => this.normalizeValue(item, depth + 1));
      if (value.length > MAX_ARRAY_ITEMS) {
        result.push(`[truncated ${value.length - MAX_ARRAY_ITEMS} more]`);
      }
      return result;
    }
    if (value instanceof Error) {
      return {
        name: this.normalizeString(value.name, 256),
        message: this.normalizeString(value.message, MAX_TEXT_CHARS),
      };
    }
    if (isPlainObject(value)) {
      const entries = Object.entries(value);
      const result = {};
      for (const [key, item] of entries.slice(0, MAX_OBJECT_PROPERTIES)) {
        result[this.normalizeString(key, 256)] = this.normalizeValue(
          item,
          depth + 1
        );
      }
      if (entries.length > MAX_OBJECT_PROPERTIES) {
        result.truncated = `[${entries.length - MAX_OBJECT_PROPERTIES} more properties]`;
      }
      return result;
    }
    return this.normalizeString(value, MAX_TEXT_CHARS);
  }

  normalizeString(value, maxChars) {
    const text = this.sanitizeOutput(String(value));
    if (text.length <= maxChars) return text;
    const suffix = `[truncated ${text.length - maxChars} chars]`;
    return `${text.slice(0, maxChars)}${suffix}`;
  }

  async write(event) {
    if (this.closed || this.writeFailed || !this.fileHandle) return;
    let serialized = `${JSON.stringify(event)}\n`;
    const eventBytes = Buffer.byteLength(serialized, "utf8");
    if (eventBytes > MAX_EVENT_BYTES) {
      const fallbackEvent = {
        ...event,
        data: {
          type: "diagnostics-event-truncated",
          original_type:
            event.data && typeof event.data.type === "string"
              ? event.data.type
              : null,
          original_bytes: eventBytes,
        },
      };
      serialized = `${JSON.stringify(fallbackEvent)}\n`;
    }
    const metadata = await this.fileHandle.stat();
    if (metadata.size >= this.maxBytes) {
      await this.rotate();
    }
    await this.fileHandle.appendFile(serialized, "utf8");
  }

  async rotate() {
    await this.fileHandle.close();
    this.fileHandle = null;
    await fs.promises.rm(this.rotatedPath(this.maxRotatedFiles), {
      force: true,
    });
    for (let index = this.maxRotatedFiles - 1; index >= 1; index -= 1) {
      await this.renameIfExists(
        this.rotatedPath(index),
        this.rotatedPath(index + 1)
      );
    }
    await fs.promises.rename(this.filePath, this.rotatedPath(1));
    this.fileHandle = await this.openLogFile();
  }

  async renameIfExists(source, destination) {
    let metadata;
    try {
      metadata = await fs.promises.lstat(source);
    } catch (error) {
      if (error.code === "ENOENT") return;
      throw error;
    }
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new Error("Desktop diagnostics rotated file is invalid");
    }
    await fs.promises.rename(source, destination);
  }

  rotatedPath(index) {
    return `${this.filePath}.${index}`;
  }

  async ensurePrivateDirectory(directory) {
    let metadata;
    try {
      metadata = await fs.promises.lstat(directory);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await fs.promises.mkdir(directory, { recursive: true });
    }
    if (metadata && (!metadata.isDirectory() || metadata.isSymbolicLink())) {
      throw new Error("Desktop diagnostics directory is invalid");
    }
    if (process.platform !== "win32") {
      await fs.promises.chmod(directory, 0o700);
    }
  }

  async openLogFile() {
    if (process.platform === "win32") {
      let metadata;
      try {
        metadata = await fs.promises.lstat(this.filePath);
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (metadata && (!metadata.isFile() || metadata.isSymbolicLink())) {
        throw new Error("Desktop diagnostics file is invalid");
      }
    }

    const flags =
      fs.constants.O_WRONLY |
      fs.constants.O_CREAT |
      fs.constants.O_APPEND |
      (process.platform === "win32" ? 0 : fs.constants.O_NOFOLLOW);
    const fileHandle = await fs.promises.open(this.filePath, flags, 0o600);
    const metadata = await fileHandle.stat();
    if (!metadata.isFile()) {
      await fileHandle.close();
      throw new Error("Desktop diagnostics file is invalid");
    }
    if (process.platform !== "win32") {
      await fs.promises.chmod(this.filePath, 0o600);
    }
    return fileHandle;
  }
}

module.exports = {
  DesktopDiagnosticsLog,
};
