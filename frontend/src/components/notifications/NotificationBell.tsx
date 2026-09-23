import { useCallback, useEffect, useState } from "react";

import {
  getUnreadNotificationCount,
  listNotifications,
  markNotificationAsRead,
} from "@/api";
import type { Notification } from "@/types";

const POLL_INTERVAL_MS = 30_000;

function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const loadNotifications = useCallback(async () => {
    try {
      const [items, count] = await Promise.all([listNotifications(), getUnreadNotificationCount()]);
      setNotifications(items);
      setUnreadCount(count);
    } catch (error) {
      console.error("Unable to load notifications:", error);
    }
  }, []);

  useEffect(() => {
    void loadNotifications();
    const intervalId = window.setInterval(() => void loadNotifications(), POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [loadNotifications]);

  async function handleNotificationClick(notification: Notification) {
    if (notification.is_read) {
      return;
    }
    try {
      const updated = await markNotificationAsRead(notification.id);
      setNotifications(items => items.map(item => (item.id === updated.id ? updated : item)));
      setUnreadCount(count => Math.max(0, count - 1));
    } catch (error) {
      console.error("Unable to mark notification as read:", error);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Notifications"
        onClick={() => setIsOpen(open => !open)}
        className="relative rounded-md p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900"
      >
        <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-red-600 px-1 text-center text-xs font-semibold leading-5 text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 z-10 mt-2 w-80 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg">
          <div className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-900">Notifications</div>
          {notifications.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-gray-500">No notifications yet.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {notifications.map(notification => (
                <li key={notification.id}>
                  <button
                    type="button"
                    onClick={() => void handleNotificationClick(notification)}
                    className={`w-full border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50 ${notification.is_read ? "bg-white" : "bg-blue-50"}`}
                  >
                    <p className="text-sm font-medium text-gray-900">{notification.title}</p>
                    <p className="mt-1 text-sm text-gray-600">{notification.message}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default NotificationBell;
