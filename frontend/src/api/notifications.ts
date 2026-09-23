import { apiClient } from "./client";
import type { Notification, NotificationUnreadCountResponse } from "@/types";

export async function listNotifications(): Promise<Notification[]> {
  const response = await apiClient.get<Notification[]>("/notifications");
  return response.data;
}

export async function getUnreadNotificationCount(): Promise<number> {
  const response = await apiClient.get<NotificationUnreadCountResponse>("/notifications/unread-count");
  return response.data.count;
}

export async function markNotificationAsRead(notificationId: string): Promise<Notification> {
  const response = await apiClient.post<Notification>(`/notifications/${notificationId}/read`);
  return response.data;
}
