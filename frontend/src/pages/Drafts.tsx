import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { deleteComposeDraft, listComposeDrafts } from "@/api/composeDrafts";
import { ApiError } from "@/api/client";
import { approveDraft, listAIDrafts } from "@/api/drafts";
import EmailBodyRenderer from "@/components/email/EmailBodyRenderer";
import type { ComposeDraft, DraftReview } from "@/types";

function Drafts() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<ComposeDraft[]>([]);
  const [aiDrafts, setAIDrafts] = useState<DraftReview[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const loadDrafts = useCallback(async () => {
    setStatus("loading");
    setError(null);
    const [composeResult, aiResult] = await Promise.allSettled([
      listComposeDrafts(),
      listAIDrafts(),
    ]);
    let failed = false;
    if (composeResult.status === "fulfilled") {
      setDrafts(composeResult.value.items);
    } else {
      failed = true;
    }
    if (aiResult.status === "fulfilled") {
      setAIDrafts(aiResult.value.items);
    } else {
      failed = true;
    }
    if (!failed) {
      setStatus("success");
    } else {
      setStatus("error");
      setError(
        [composeResult, aiResult].some(
          (result) =>
            result.status === "rejected" &&
            result.reason instanceof ApiError &&
            result.reason.status === 401,
        )
          ? "Your session expired. Please sign in again."
          : "Unable to load drafts. Please try again.",
      );
    }
  }, []);

  useEffect(() => {
    void loadDrafts();
  }, [loadDrafts]);

  async function handleDelete(draftId: string) {
    if (deletingId) return;
    setDeletingId(draftId);
    try {
      await deleteComposeDraft(draftId);
      setDrafts((current) => current.filter((draft) => draft.id !== draftId));
    } catch {
      setError("Unable to delete this draft. Please try again.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleApprove(draftId: string) {
    if (approvingId) return;
    setApprovingId(draftId);
    try {
      await approveDraft(draftId);
      setAIDrafts((current) => current.filter((draft) => draft.id !== draftId));
    } catch {
      setError("Unable to approve and send this draft. Please try again.");
    } finally {
      setApprovingId(null);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6 flex items-center justify-between">
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-gray-900">← Back to Dashboard</Link>
          <h1 className="text-2xl font-bold text-gray-900">Drafts</h1>
          <button type="button" onClick={() => navigate("/compose")} className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors">
            New draft
          </button>
        </div>

        {status === "loading" && <p className="py-12 text-center text-gray-600">Loading drafts...</p>}
        {status === "error" && (
          <div className="mb-6 border-l-4 border-red-400 bg-red-50 p-4 rounded-r-lg">
            <p className="text-red-700">{error}</p>
            <button type="button" onClick={() => void loadDrafts()} className="mt-2 rounded-md bg-red-100 px-3 py-2 text-red-800 hover:bg-red-200 transition-colors">Retry</button>
          </div>
        )}
        {status === "success" && drafts.length === 0 && aiDrafts.length === 0 && (
          <div className="py-16 text-center">
            <svg className="mx-auto h-12 w-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <p className="mt-3 text-gray-500 font-medium">No saved drafts yet.</p>
            <p className="mt-1 text-sm text-gray-400">AI-generated drafts and your compose drafts will appear here.</p>
          </div>
        )}

        {/* AI-generated drafts for review */}
        {aiDrafts.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-4 text-lg font-semibold text-gray-900 flex items-center gap-2">
              <span className="inline-flex h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              AI Drafts for Review
              <span className="text-sm font-normal text-gray-500">({aiDrafts.length})</span>
            </h2>
            <div className="space-y-5">
              {aiDrafts.map((draft) => (
                <article key={draft.id} className="rounded-xl border border-blue-200 bg-white shadow-sm overflow-hidden">
                  {/* Original email section */}
                  <div className="bg-gray-50 px-5 py-4 border-b border-gray-100">
                    <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Original Email</p>
                    <p className="font-medium text-gray-900">{draft.email.subject || "(No subject)"}</p>
                    <p className="text-sm text-gray-500 mt-0.5">From: {draft.email.sender}</p>
                    <div className="mt-3 rounded-lg bg-white border border-gray-100 p-4 max-h-64 overflow-y-auto">
                      <EmailBodyRenderer
                        bodyHtml={draft.email.body_html}
                        bodyText={draft.email.body_text || draft.email.snippet}
                        fallback="(No email content)"
                      />
                    </div>
                  </div>

                  {/* Generated reply section */}
                  <div className="px-5 py-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-blue-600 mb-2">Generated Reply</p>
                    <div className="rounded-lg bg-blue-50 border border-blue-100 p-4">
                      <EmailBodyRenderer
                        bodyText={draft.body}
                        fallback="(Empty draft)"
                      />
                    </div>
                    <div className="mt-4 flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => void handleApprove(draft.id)}
                        disabled={approvingId === draft.id}
                        className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                      >
                        {approvingId === draft.id ? "Sending..." : "✓ Approve and Send"}
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {/* Compose drafts */}
        {drafts.length > 0 && (
          <section>
            <h2 className="mb-4 text-lg font-semibold text-gray-900">
              Compose Drafts
              <span className="ml-2 text-sm font-normal text-gray-500">({drafts.length})</span>
            </h2>
            <div className="space-y-3">
            {drafts.map((draft) => (
              <div key={draft.id} className="flex items-center justify-between rounded-lg bg-white p-4 shadow-sm border border-gray-100 hover:border-gray-200 transition-colors">
                <button type="button" onClick={() => navigate(`/compose?draft=${draft.id}`)} className="min-w-0 flex-1 text-left">
                  <p className="truncate font-medium text-gray-900">{draft.subject || "(No subject)"}</p>
                  <p className="truncate text-sm text-gray-600">{draft.body_text || draft.body_html || "(Empty draft)"}</p>
                  <p className="mt-1 text-xs text-gray-400">Updated {new Date(draft.updated_at).toLocaleString()}</p>
                </button>
                <button type="button" onClick={() => void handleDelete(draft.id)} disabled={deletingId === draft.id} className="ml-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors">
                  {deletingId === draft.id ? "Deleting..." : "Delete"}
                </button>
              </div>
            ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export default Drafts;