import { describe, expect, it } from "vitest";

import { homeViewHash, parseHomeView } from "./homeView";

describe("parseHomeView", () => {
  it("recognizes supported hash views", () => {
    expect(parseHomeView("#agent-team")).toBe("agent-team");
    expect(parseHomeView("#senza")).toBe("senza");
  });

  it("falls back to Senza for empty or unknown views", () => {
    expect(parseHomeView("")).toBe("senza");
    expect(parseHomeView("#unknown")).toBe("senza");
  });
});

describe("homeViewHash", () => {
  it("builds canonical hashes", () => {
    expect(homeViewHash("agent-team")).toBe("#agent-team");
    expect(homeViewHash("senza")).toBe("#senza");
  });
});
