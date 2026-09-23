export interface Notification {
  id: string;
  email_id: string;
  notification_type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface NotificationUnreadCountResponse {
  count: number;
}
