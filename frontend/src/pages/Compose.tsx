import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCallback } from "react";

import {
  createComposeDraft,
  generateEmailContent,
  getAIStatus,
  getComposeDraft,
  gmailSend,
  updateComposeDraft,
} from "@/api";
import { ApiError } from "@/api/client";

type ComposeStatus = "idle" | "generating" | "saving" | "sending" | "success" | "error";

interface ComposeFormValues {
  to: string;
  subject: string;
  body: string;
}

function Compose() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [formValues, setFormValues] = useState<ComposeFormValues>({to: "", subject: "", body: ""});
  const [status, setStatus] = useState<ComposeStatus>("idle");
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [generatedBody, setGeneratedBody] = useState<string>("");
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(searchParams.get("draft"));

  useEffect(() => {
    let active = true;
    void getAIStatus()
      .then((result) => {
        if (active) setAiStatus(result.status);
      })
      .catch(() => {
        if (active) setAiStatus("provider_error");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const requestedDraftId = searchParams.get("draft");
    if (!requestedDraftId) return;
    let active = true;
    void getComposeDraft(requestedDraftId)
      .then((draft) => {
        if (!active) return;
        setDraftId(draft.id);
        setFormValues({
          to: draft.recipients.join(", "),
          subject: draft.subject,
          body: draft.body_text ?? draft.body_html ?? "",
        });
      })
      .catch(() => {
        if (active) {
          setStatus("error");
          setStatusMessage("Unable to load this draft. Please try again.");
        }
      });
    return () => {
      active = false;
    };
  }, [searchParams]);

  const handleGenerateAI = useCallback(async () => {
    if (aiStatus && aiStatus !== "available") {
      setStatusMessage(
        aiStatus === "not_configured"
          ? "AI is not configured. Set GROQ_API_KEY in backend/.env and restart the backend."
          : aiStatus === "authentication_error"
            ? "The AI provider rejected its API key. Check the backend configuration."
            : "The AI service is temporarily unavailable. Please try again.",
      );
      setStatus("error");
      return;
    }
    if (!formValues.to && !formValues.subject && !formValues.body) {
      setStatusMessage("Please enter some content to generate from");
      setStatus("error");
      return;
    }

    setStatus("generating");
    setStatusMessage("Generating email content...");
    try {
      // Call backend to generate email content from intent
      const response = await generateEmailContent({
        to: formValues.to,
        subject: formValues.subject,
        body: formValues.body,
        instructions: "Generate a professional email based on the provided content"
      });

      setGeneratedBody(`${response.subject}\n\n`.trim());
      setFormValues((prev) => ({
        ...prev,
        subject: response.subject,
        body: response.body
      }));
      setStatus("success");
      setStatusMessage("Email content generated successfully");
    } catch (err) {
      console.error("Generation failed:", err);
      setStatus("error");
      setStatusMessage(
        err instanceof ApiError && [502, 529].includes(err.status)
          ? "AI service is temporarily unavailable. Please try again."
          : err instanceof ApiError && err.status === 503
            ? "AI generation is not configured. Set GROQ_API_KEY in backend/.env and restart the backend."
          : "Failed to generate email content. Please try again.",
      );
    }
  }, [aiStatus, formValues]);

  const handleSaveDraft = useCallback(async () => {
    setStatus("saving");
    setStatusMessage("Saving draft...");
    try {
      const payload = {
        recipients: formValues.to
          .split(",")
          .map((recipient) => recipient.trim())
          .filter(Boolean),
        subject: formValues.subject.trim(),
        body_text: formValues.body || null,
      };
      const savedDraft = draftId
        ? await updateComposeDraft(draftId, payload)
        : await createComposeDraft(payload);
      setDraftId(savedDraft.id);
      setStatusMessage("Draft saved successfully");
      setStatus("success");
    } catch (err: unknown) {
      console.error("Save failed:", err);
      setStatus("error");
      setStatusMessage("Failed to save draft. Please try again.");
    }
  }, [draftId, formValues]);

  const handleSend = useCallback(async () => {
    const recipient = formValues.to.trim();
    const emailRegex = /^[^\s@]+(?:\.[^\s@]+)*@[^\s@]+(?:\.[^\s@]+)+$/;
    if (!formValues.subject.trim()) {
      setStatusMessage("Subject is required");
      setStatus("error");
      return;
    }
    if (!recipient) {
      setStatusMessage("To field is required");
      setStatus("error");
      return;
    }
    if (!emailRegex.test(recipient)) {
      setStatusMessage("Please enter a valid email address");
      setStatus("error");
      return;
    }

    if (!formValues.body.trim()) {
      setStatusMessage("Cannot send empty email");
      setStatus("error");
      return;
    }

    setStatus("sending");
    setStatusMessage("Sending email...");
    try {
      // Send via Gmail API
      const response = await gmailSend({
        to: [recipient],
        subject: formValues.subject,
        body_text: formValues.body
      });

      if (!response.success) {
        throw new Error("Gmail did not accept the message for sending.");
      }
      setStatus("success");
      setStatusMessage("Email accepted for sending. Delivery is not guaranteed.");

      // Reset form after successful send
      setTimeout(() => {
        setFormValues({ to: "", subject: "", body: "" });
        setStatus("idle");
        setStatusMessage("");
        setGeneratedBody("");
      }, 2000);
    } catch (err: unknown) {
      console.error("Send failed:", err);
      setStatus("error");
      setStatusMessage("Failed to send email. Please try again.");
    }
  }, [formValues]);

  const handleDiscard = useCallback(() => {
    setFormValues({ to: "", subject: "", body: "" });
    setStatus("idle");
    setStatusMessage("");
    setGeneratedBody("");
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-6 flex items-center justify-between">
          <button
            onClick={() => navigate("/inbox")}
            className="flex items-center text-sm text-gray-600 hover:text-gray-900"
          >
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
            </svg>
            Back to Inbox
          </button>
          <Link to="/drafts" className="text-sm text-gray-600 hover:text-gray-900">Drafts</Link>
          <h1 className="text-2xl font-bold text-gray-900">Compose Email</h1>
        </div>

        {status === "error" && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
            <p className="text-red-700">{statusMessage}</p>
            <button
              type="button"
              onClick={() => setStatus("idle")}
              className="mt-2 inline-flex items-center px-3 py-2 bg-red-100 text-red-800 font-medium rounded-md hover:bg-red-200"
            >
              Dismiss
            </button>
          </div>
        )}

        {status === "success" && (
          <div className="bg-green-50 border-l-4 border-green-400 p-4 mb-6">
            <p className="text-green-700">{statusMessage}</p>
            <button
              type="button"
              onClick={() => setStatus("idle")}
              className="mt-2 inline-flex items-center px-3 py-2 bg-green-100 text-green-800 font-medium rounded-md hover:bg-green-200"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">To</label>
            <input
              value={formValues.to}
              onChange={(e) => setFormValues((prev) => ({ ...prev, to: e.target.value }))}
              placeholder="recipient@example.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Subject</label>
            <input
              value={formValues.subject}
              onChange={(e) => setFormValues((prev) => ({ ...prev, subject: e.target.value }))}
              placeholder="Email subject"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Message</label>
            <textarea
              value={formValues.body}
              onChange={(e) => setFormValues((prev) => ({ ...prev, body: e.target.value }))}
              placeholder="Type your message here..."
              className="w-full min-h-[200px] px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all resize-y"
              rows={10}
            />
          </div>

          <div className="flex items-center space-x-4">
            <button
              type="button"
              onClick={handleGenerateAI}
              disabled={(aiStatus !== null && aiStatus !== "available") || status === "generating" || status === "sending"}
              className="flex-1 px-4 py-2 bg-blue-50 hover:bg-blue-100 text-blue-800 font-medium rounded-lg transition-colors"
            >
              {aiStatus !== null && aiStatus !== "available" ? (
                aiStatus === "not_configured" ? "AI not configured" : "AI temporarily unavailable"
              ) : status === "generating" ? (
                <>
                  <svg className="w-4 h-4 mr-2 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l4 4H6l4-4z" />
                  </svg>
                  Generating...
                </>
              ) : (
                "Generate with AI"
              )}
            </button>

            <button
              type="button"
              onClick={handleSaveDraft}
              disabled={status === "saving" || status === "sending"}
              className="flex-1 px-4 py-2 bg-green-50 hover:bg-green-100 text-green-800 font-medium rounded-lg transition-colors"
            >
              {status === "saving" ? "Saving..." : "Save Draft"}
            </button>

            <button
              type="button"
              onClick={handleSend}
              disabled={status === "sending" || !formValues.to.trim() || !formValues.body.trim()}
              className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
            >
              {status === "sending" ? "Sending..." : "Send"}
            </button>

            <button
              type="button"
              onClick={handleDiscard}
              className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium rounded-lg transition-colors"
            >
              Discard
            </button>
          </div>
        </div>

        {generatedBody && status !== "generating" && (
          <div className="mt-6 p-4 bg-white rounded-xl shadow-md">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Generated Preview</h2>
            <div className="whitespace-pre-wrap break-words text-gray-700">
              {generatedBody}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Compose;
