import { describe, expect, it, vi } from "vitest";

import type { Notification } from "@/types";
import { apiClient } from "./client";
import {
  getUnreadNotificationCount,
  listNotifications,
  markNotificationAsRead,
} from "./notifications";

vi.mock("./client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe("notification API", () => {
  it("lists notifications and reads the unread count", async () => {
    const notifications: Notification[] = [];
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: notifications } as never)
      .mockResolvedValueOnce({ data: { count: 2 } } as never);

    await expect(listNotifications()).resolves.toEqual(notifications);
    await expect(getUnreadNotificationCount()).resolves.toBe(2);
    expect(apiClient.get).toHaveBeenNthCalledWith(1, "/notifications");
    expect(apiClient.get).toHaveBeenNthCalledWith(2, "/notifications/unread-count");
  });

  it("marks a notification as read", async () => {
    const notification = { id: "notification-1", is_read: true };
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: notification } as never);

    await expect(markNotificationAsRead("notification-1")).resolves.toEqual(notification);
    expect(apiClient.post).toHaveBeenCalledWith("/notifications/notification-1/read");
  });
});
