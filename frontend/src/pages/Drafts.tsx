import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { deleteComposeDraft, listComposeDrafts } from "@/api/composeDrafts";
import { ApiError } from "@/api/client";
import type { ComposeDraft } from "@/types";

function Drafts() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<ComposeDraft[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadDrafts = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const result = await listComposeDrafts();
      setDrafts(result.items);
      setStatus("success");
    } catch (requestError) {
      setStatus("error");
      setError(
        requestError instanceof ApiError && requestError.status === 401
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

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6 flex items-center justify-between">
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-gray-900">Back to Dashboard</Link>
          <h1 className="text-2xl font-bold text-gray-900">Drafts</h1>
          <button type="button" onClick={() => navigate("/compose")} className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white">
            New draft
          </button>
        </div>

        {status === "loading" && <p className="py-12 text-center text-gray-600">Loading drafts...</p>}
        {status === "error" && (
          <div className="mb-6 border-l-4 border-red-400 bg-red-50 p-4">
            <p className="text-red-700">{error}</p>
            <button type="button" onClick={() => void loadDrafts()} className="mt-2 rounded-md bg-red-100 px-3 py-2 text-red-800">Retry</button>
          </div>
        )}
        {status === "success" && drafts.length === 0 && (
          <p className="py-12 text-center text-gray-600">No saved drafts yet.</p>
        )}
        {status === "success" && drafts.length > 0 && (
          <div className="space-y-3">
            {drafts.map((draft) => (
              <div key={draft.id} className="flex items-center justify-between rounded-lg bg-white p-4 shadow-sm">
                <button type="button" onClick={() => navigate(`/compose?draft=${draft.id}`)} className="min-w-0 flex-1 text-left">
                  <p className="truncate font-medium text-gray-900">{draft.subject || "(No subject)"}</p>
                  <p className="truncate text-sm text-gray-600">{draft.body_text || draft.body_html || "(Empty draft)"}</p>
                  <p className="mt-1 text-xs text-gray-400">Updated {new Date(draft.updated_at).toLocaleString()}</p>
                </button>
                <button type="button" onClick={() => void handleDelete(draft.id)} disabled={deletingId === draft.id} className="ml-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 disabled:opacity-50">
                  {deletingId === draft.id ? "Deleting..." : "Delete"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Drafts;