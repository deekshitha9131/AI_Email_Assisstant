import { describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import { approveDraft, listAIDrafts } from "./drafts";

vi.mock("./client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

describe("AI draft API", () => {
  it("lists reviewable AI drafts from the drafts endpoint", async () => {
    const payload = { items: [], page: 1, page_size: 25 };
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: payload } as never);

    await expect(listAIDrafts()).resolves.toEqual(payload);
    expect(apiClient.get).toHaveBeenCalledWith("/drafts");
  });

  it("posts explicit approval to the draft approval endpoint", async () => {
    const payload = {
      id: "draft-1",
      email_id: "email-1",
      body: "Reply",
      status: "sent",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: payload } as never);

    await expect(approveDraft("draft-1")).resolves.toEqual(payload);
    expect(apiClient.post).toHaveBeenCalledWith("/drafts/draft-1/approve");
  });
});
