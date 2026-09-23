import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listSentEmails } from "@/api/sent";
import { ApiError } from "@/api/client";
import type { SentEmail } from "@/types";

function Sent() {
  const [messages, setMessages] = useState<SentEmail[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [pageTokens, setPageTokens] = useState<string[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  const loadMessages = useCallback(async (pageToken?: string) => {
    setStatus("loading");
    setError(null);
    try {
      const result = await listSentEmails({ page_token: pageToken, page_size: 25 });
      setMessages(result.items);
      setNextPageToken(result.next_page_token ?? null);
      setStatus("success");
    } catch (reason) {
      setStatus("error");
      setError(
        reason instanceof ApiError && reason.status === 401
          ? "Your session expired. Please sign in again."
          : "Unable to load sent mail. Please try again.",
      );
    }
  }, []);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  function goToNextPage() {
    if (!nextPageToken) return;
    setPageTokens((current) => [...current, nextPageToken]);
    void loadMessages(nextPageToken);
  }

  function goToPreviousPage() {
    const previousToken = pageTokens.at(-2);
    setPageTokens((current) => current.slice(0, -1));
    void loadMessages(previousToken);
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-gray-900">Back to Dashboard</Link>
          <h1 className="text-2xl font-bold text-gray-900">Sent</h1>
          <Link to="/compose" className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white">Compose</Link>
        </div>

        {status === "loading" && <p className="py-12 text-center text-gray-600">Loading sent mail...</p>}
        {status === "error" && (
          <div className="mb-6 border-l-4 border-red-400 bg-red-50 p-4">
            <p className="text-red-700">{error}</p>
            <button type="button" onClick={() => void loadMessages(pageTokens.at(-1))} className="mt-2 rounded-md bg-red-100 px-3 py-2 text-red-800">Retry</button>
          </div>
        )}
        {status === "success" && messages.length === 0 && (
          <p className="py-12 text-center text-gray-600">No sent messages yet.</p>
        )}
        {status === "success" && messages.length > 0 && (
          <>
            <div className="space-y-3">
              {messages.map((message) => (
                <article key={message.gmail_message_id} className="rounded-lg bg-white p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-gray-900">To {message.recipients.join(", ") || "(No recipient)"}</p>
                      <p className="truncate text-sm text-gray-700">{message.subject || "(No subject)"}</p>
                    </div>
                    <time className="shrink-0 text-xs text-gray-400" dateTime={message.sent_at}>{new Date(message.sent_at).toLocaleString()}</time>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm text-gray-600">{message.body_text || message.snippet || "(No message content)"}</p>
                  <p className="mt-3 text-xs text-gray-400">Message {message.gmail_message_id} · Thread {message.gmail_thread_id}</p>
                </article>
              ))}
            </div>
            <div className="mt-6 flex items-center justify-between">
              <button type="button" onClick={goToPreviousPage} disabled={pageTokens.length === 0} className="rounded-md bg-gray-100 px-3 py-2 text-sm text-gray-700 disabled:opacity-50">Previous</button>
              <span className="text-sm text-gray-500">Sent mail</span>
              <button type="button" onClick={goToNextPage} disabled={!nextPageToken} className="rounded-md bg-gray-100 px-3 py-2 text-sm text-gray-700 disabled:opacity-50">Next</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default Sent;
