import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { analyzeEmail, createDraft } from "@/api";
import { ApiError } from "@/api/client";
import DraftEditor from "@/components/draft/DraftEditor";
import EmailDetailView from "@/components/email/EmailDetailView";
import { useEmailDetail } from "@/hooks/useEmailDetail";
import type { AIUnderstandingResult, Draft } from "@/types";

type DraftGenerationStatus = "idle" | "generating" | "success" | "not_analyzed" | "error";

function describeAnalysisError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "AI_CONFIGURATION_ERROR":
        return "AI is not configured. Set GROQ_API_KEY in backend/.env and restart the backend.";
      case "AI_AUTHENTICATION_ERROR":
        return "The AI provider rejected its API key. Check the backend configuration.";
      case "AI_TIMEOUT":
        return "The AI request timed out. Please try again.";
      case "AI_PROVIDER_ERROR":
        return error.message;
      case "AI_INVALID_RESPONSE":
        return error.message;
      default:
        return error.message || "AI analysis failed. Please try again.";
    }
  }
  return "AI analysis failed due to an unexpected error. Please try again.";
}

function describeDraftError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "DRAFT_UNDERSTANDING_MISSING":
        return "Analyze the email with AI before generating a reply.";
      case "AI_PROVIDER_ERROR":
        return `Draft generation failed: ${error.message}`;
      case "AI_CONFIGURATION_ERROR":
        return "AI is not configured. Set GROQ_API_KEY in backend/.env and restart the backend.";
      case "AI_TIMEOUT":
        return "The AI request timed out while generating the reply. Please try again.";
      case "DRAFT_STATUS_ERROR":
        return error.message;
      default:
        return error.message || "Unable to generate a reply. Please try again.";
    }
  }
  return "Unable to generate a reply due to an unexpected error. Please try again.";
}

function EmailDetail() {
  const { emailId } = useParams<{ emailId: string }>();
  const { status, email, retry } = useEmailDetail(emailId ?? "");
  const [draftStatus, setDraftStatus] = useState<DraftGenerationStatus>("idle");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [analysisResult, setAnalysisResult] = useState<AIUnderstandingResult | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const handleGenerateDraft = useCallback(async () => {
    if (!email || draftStatus === "generating") return;
    setDraftStatus("generating");
    setDraftError(null);
    try {
      const generated = await createDraft({ email_id: email.id });
      setDraft(generated);
      setDraftStatus("success");
    } catch (error) {
      if (error instanceof ApiError && error.code === "DRAFT_UNDERSTANDING_MISSING") {
        setDraftStatus("not_analyzed");
      } else {
        setDraftStatus("error");
      }
      setDraftError(describeDraftError(error));
    }
  }, [draftStatus, email]);

  const handleAnalyzeEmail = useCallback(async () => {
    if (!email || !emailId || analysisStatus === "loading") return;
    setAnalysisStatus("loading");
    setAnalysisError(null);
    try {
      const result = await analyzeEmail(emailId);
      setAnalysisResult(result);
      setAnalysisStatus("success");
    } catch (error) {
      console.error("AI analysis failed:", error);
      setAnalysisStatus("error");
      setAnalysisError(describeAnalysisError(error));
    }
  }, [analysisStatus, email, emailId]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6 flex items-center justify-between">
          <Link to="/inbox" className="flex items-center text-sm text-gray-600 hover:text-gray-900">
            Back to Inbox
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">Email Details</h1>
        </div>

        {status === "loading" && <p className="text-center py-12 text-gray-600">Loading email...</p>}
        {status === "not_found" && <p className="text-center py-12 text-gray-600">This email is not available.</p>}
        {status === "error" && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
            <p className="text-red-700">We could not load this email. Please try again.</p>
            <button type="button" onClick={retry} className="mt-2 px-3 py-2 bg-red-100 text-red-800 rounded-md">
              Retry
            </button>
          </div>
        )}

        {status === "success" && email && (
          <>
            <div className="mb-6">
              <EmailDetailView email={email} />
            </div>

            <section className="mb-6 space-y-4">
              <button
                type="button"
                onClick={handleAnalyzeEmail}
                disabled={analysisStatus === "loading"}
                className="w-full px-4 py-2 bg-blue-50 hover:bg-blue-100 text-blue-800 font-medium rounded-lg"
              >
                {analysisStatus === "loading" ? "Analyzing..." : "Analyze with AI"}
              </button>
              {analysisStatus === "success" && analysisResult && (
                <div className="p-4 bg-white rounded-xl shadow-md space-y-2">
                  <h2 className="text-lg font-semibold text-gray-900">AI Analysis</h2>
                  <p className="text-sm text-gray-600">{analysisResult.summary}</p>
                  <p className="text-sm text-gray-600">Category: {analysisResult.category}</p>
                  <p className="text-sm text-gray-600">Sentiment: {analysisResult.sentiment}</p>
                </div>
              )}
              {analysisStatus === "error" && (
                <div className="bg-red-50 border-l-4 border-red-400 p-4">
                  <p className="text-red-700">{analysisError}</p>
                </div>
              )}
            </section>

            {!draft && (
              <button
                type="button"
                onClick={handleGenerateDraft}
                disabled={draftStatus === "generating"}
                className="w-full px-4 py-2 bg-green-50 hover:bg-green-100 text-green-800 font-medium rounded-lg"
              >
                {draftStatus === "generating" ? "Generating reply..." : "Generate Reply"}
              </button>
            )}
            {draftStatus === "not_analyzed" && (
              <p className="mt-3 text-amber-700 bg-amber-50 border-l-4 border-amber-400 p-3">
                {draftError || "Analyze the email before generating a reply."}
              </p>
            )}
            {draftStatus === "error" && (
              <div className="mt-3 bg-red-50 border-l-4 border-red-400 p-3">
                <p className="text-red-700">{draftError || "Unable to generate a reply."}</p>
              </div>
            )}
            {draft && <div className="mt-6"><DraftEditor draft={draft} onDraftChange={setDraft} /></div>}
          </>
        )}
      </div>
    </div>
  );
}

export default EmailDetail;