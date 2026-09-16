import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

afterEach(() => {
  fetchMock.mockReset();
});

describe("Agent Team API client", () => {
  it("loads issues through the backend proxy", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ issues: [] }));

    await expect(api.listAgentTeamIssues("team one")).resolves.toEqual({
      issues: [],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/team/issues?project=team%20one",
      { credentials: "same-origin" }
    );
  });

  it("confirms and rejects issues with POST requests", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ok: true, project: "p", id: "I-1", status: "confirmed" })
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ok: true, project: "p", id: "I-1", status: "rejected" })
    );

    await api.confirmAgentTeamIssue("I-1");
    await api.rejectAgentTeamIssue("I-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/team/issue/I-1/confirm",
      { method: "POST", credentials: "same-origin" }
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/team/issue/I-1/reject",
      { method: "POST", credentials: "same-origin" }
    );
  });

  it("loads member config and session history", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        model: "model",
        system_prompt: "prompt",
        tools: ["tool"],
        thinking_level: "Medium",
        temperature: 0.2,
        override: null,
      })
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ lines: [] }));

    await api.getAgentTeamAgentConfig("team one", "planner");
    await api.getAgentTeamAgentSession("team one", "planner");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/team/agent/config?project=team%20one&agent=planner",
      { credentials: "same-origin" }
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/team/agent/session?project=team%20one&agent=planner",
      { credentials: "same-origin" }
    );
  });

  it("updates member config without echoing an API key", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true, rebuilt: true }));

    await api.updateAgentTeamAgentConfig({
      project: "p",
      agent: "planner",
      persona: "updated",
      model: "main",
      base_url: "http://127.0.0.1:9",
      api_key: "secret",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/team/agent/config",
      expect.objectContaining({
        method: "PUT",
        credentials: "same-origin",
      })
    );
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      project: "p",
      agent: "planner",
      persona: "updated",
      model: "main",
      base_url: "http://127.0.0.1:9",
      api_key: "secret",
    });
  });
});
