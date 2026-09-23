import { describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import { listSentEmails } from "./sent";

vi.mock("./client", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

describe("Sent email API", () => {
  it("lists sent messages with Gmail pagination", async () => {
    const payload = { items: [], next_page_token: "next-token" };
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: payload } as never);

    await expect(listSentEmails({ page_token: "previous-token", page_size: 25 })).resolves.toEqual(payload);
    expect(apiClient.get).toHaveBeenCalledWith("/gmail/sent", {
      params: { page_token: "previous-token", page_size: 25 },
    });
  });
});