import { createRequire } from "node:module";
import net from "node:net";
import { test } from "vitest";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const {
  backendUrlFromPort,
  findAvailableBackendPort,
  normalizeBackendPort,
  selectBackendPort,
} = require("./backend-port.cjs");

test("uses the default backend port", () => {
  assert.equal(normalizeBackendPort(undefined), 7878);
  assert.equal(normalizeBackendPort(""), 7878);
});

test("accepts a valid backend port", () => {
  assert.equal(normalizeBackendPort("9000"), 9000);
  assert.equal(backendUrlFromPort(9000), "http://127.0.0.1:9000");
});

test("rejects invalid backend ports", () => {
  assert.throws(() => normalizeBackendPort("7878.1"), /integer/u);
  assert.throws(() => normalizeBackendPort("0"), /between/u);
  assert.throws(() => normalizeBackendPort("65536"), /between/u);
});

test("selects another available port when the preferred port is occupied", async () => {
  const blocker = net.createServer();
  await new Promise((resolve, reject) => {
    blocker.once("error", reject);
    blocker.listen(0, "127.0.0.1", resolve);
  });
  const preferredPort = blocker.address().port;

  try {
    const port = await selectBackendPort(undefined, preferredPort);
    assert.notEqual(port, preferredPort);
    const server = net.createServer();

    try {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, "127.0.0.1", resolve);
      });
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }
});

test("uses an explicitly configured port", async () => {
  assert.equal(await selectBackendPort("9000"), 9000);
});
