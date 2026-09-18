"use strict";

const net = require("net");

function normalizeBackendPort(value, fallbackPort = 7878) {
  if (value === undefined || value === null || value === "") {
    return fallbackPort;
  }
  if (!/^\d+$/.test(value)) {
    throw new Error("SENZA_STUDIO_PORT must be an integer");
  }
  const port = Number(value);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("SENZA_STUDIO_PORT must be between 1 and 65535");
  }
  return port;
}

function backendUrlFromPort(port) {
  return `http://127.0.0.1:${port}`;
}

function listenOnBackendPort(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const address = server.address();
      if (
        !address ||
        typeof address !== "object" ||
        !Number.isSafeInteger(address.port)
      ) {
        server.close(() =>
          reject(new Error("Could not allocate a backend port"))
        );
        return;
      }
      const { port } = address;
      server.close(() => resolve(port));
    });
  });
}

async function findAvailableBackendPort(preferredPort = 7878) {
  try {
    return await listenOnBackendPort(preferredPort);
  } catch (error) {
    if (error.code !== "EADDRINUSE") throw error;
    return listenOnBackendPort(0);
  }
}

async function selectBackendPort(configuredPort, preferredPort = 7878) {
  if (
    configuredPort !== undefined &&
    configuredPort !== null &&
    configuredPort !== ""
  ) {
    return normalizeBackendPort(configuredPort);
  }
  return findAvailableBackendPort(preferredPort);
}

module.exports = {
  backendUrlFromPort,
  findAvailableBackendPort,
  normalizeBackendPort,
  selectBackendPort,
};
