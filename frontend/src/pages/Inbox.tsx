import { useCallback, useEffect, useRef, useState } from "react";

import EmailList from "@/components/email/EmailList";
import { gmailIncrementalSync } from "@/api";
import { ApiError } from "@/api/client";
import { loginUrl } from "@/api/auth";
import { useAuth } from "@/hooks/useAuth";
import { useEmails } from "@/hooks/useEmails";

function Inbox() {
  const { user } = useAuth();
  const [searchQuery, setSearchQuery] = useState("");
  const { status, emails, page, pageSize, total, isEmpty, errorMessage, setPage, retry, refresh } =
    useEmails({ search: searchQuery });
  const [syncStatus, setSyncStatus] = useState("idle");
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState("Syncing your emails...");
  const syncedUserId = useRef<string | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Reset to first page when search query changes
  useEffect(() => {
    setPage(1);
  }, [searchQuery, setPage]);

  function describeSyncError(error: unknown): string {
    if (!(error instanceof ApiError)) return "Inbox sync failed unexpectedly. Check the backend logs.";
    switch (error.code) {
      case "GMAIL_NOT_CONNECTED":
        return "Gmail is not connected. Connect Gmail before syncing your inbox.";
      case "GMAIL_AUTHENTICATION_FAILED":
        return "Gmail authorization expired or was revoked. Reconnect Gmail to continue.";
      case "GMAIL_PERMISSION_DENIED":
        return "Gmail access does not include the required permission. Reconnect Gmail and approve Gmail access.";
      case "GMAIL_API_ERROR":
        return error.message;
      case "GMAIL_SYNC_ALREADY_RUNNING":
        return "An inbox sync is already running. Wait for it to finish before starting another.";
      default:
        return error.message || "Inbox sync failed. Check the backend logs for details.";
    }
  }

  const syncInitialEmails = useCallback(async () => {
    setSyncStatus("syncing");
    setSyncError(null);
    setSyncMessage("Syncing your emails...");
    try {
      await gmailIncrementalSync();
      setSyncStatus("success");
      refresh();
    } catch (error) {
      console.error("Gmail sync failed:", error);
      setSyncStatus("error");
      setSyncError(describeSyncError(error));
    }
  }, [refresh]);

  useEffect(() => {
    if (!user || syncedUserId.current === user.id) {
      return;
    }

    syncedUserId.current = user.id;
    void syncInitialEmails();
  }, [syncInitialEmails, user]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Inbox</h1>
              <div className="mt-2 flex items-center space-x-3">
                <input
                  type="text"
                  placeholder="Search emails..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === "Enter") {
                      // Reset to first page when searching
                      setPage(1);
                    }
                  }}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                </input>
                {searchQuery.trim() !== "" && (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchQuery("");
                      setPage(1); // Reset to first page when clearing search
                    }}
                    className="text-sm text-gray-500 hover:text-gray-700"
                  >
                    ×
                  </button>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={syncInitialEmails}
              disabled={syncStatus === "syncing"}
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {syncStatus === "syncing" ? "Syncing..." : "Sync inbox"}
            </button>
          </div>
        </div>

        {syncStatus === "syncing" && (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto" />
            <p className="mt-4 text-gray-600">{syncMessage}</p>
          </div>
        )}

        {syncStatus === "error" && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
            <p className="text-red-700">{syncError}</p>
            {(syncError?.includes("authorization") || syncError?.includes("Connect Gmail")) && (
              <a
                href={loginUrl}
                className="mt-2 inline-flex items-center px-3 py-2 bg-blue-100 text-blue-800 font-medium rounded-md hover:bg-blue-200"
              >
                Reconnect Gmail
              </a>
            )}
            {!syncError?.includes("expired") && (
              <button
                type="button"
                onClick={syncInitialEmails}
                className="mt-2 inline-flex items-center px-3 py-2 bg-red-100 text-red-800 font-medium rounded-md hover:bg-red-200"
              >
                Retry Sync
              </button>
            )}
          </div>
        )}

        {status === "loading" && (
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto" />
            <p className="mt-4 text-gray-600">Loading your inbox...</p>
          </div>
        )}

        {status === "error" && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
            <p className="text-red-700">{errorMessage}</p>
            <button
              type="button"
              onClick={retry}
              className="mt-2 inline-flex items-center px-3 py-2 bg-red-100 text-red-800 font-medium rounded-md hover:bg-red-200"
            >
              Retry
            </button>
          </div>
        )}

        {status === "success" && isEmpty && syncStatus !== "error" && (
          <div className="text-center py-12">
            <p className="mt-4 text-gray-600">
              {user
                ? "Your inbox is empty. Emails will appear here once they arrive in your Gmail account."
                : "Please connect your Gmail account to see your emails here."}
            </p>
          </div>
        )}

        {status === "success" && !isEmpty && (
          <>
            <div className="mb-4">
              <EmailList emails={emails} />
            </div>
            <div className="flex items-center justify-between px-4">
              <div className="text-sm text-gray-500">
                Showing {emails.length} of {total} emails
              </div>
              <div className="flex items-center space-x-3">
                <button
                  type="button"
                  onClick={() => setPage(page - 1)}
                  disabled={page <= 1}
                  className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-md disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="px-3 py-1 bg-white text-gray-600 rounded-md">
                  Page {page} of {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage(page + 1)}
                  disabled={page >= totalPages}
                  className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-md disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default Inbox;
