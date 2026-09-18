import DOMPurify from "dompurify";

import type { EmailDetail } from "@/types";

interface EmailDetailViewProps {
  email: EmailDetail;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function decodeHtmlEntities(value: string): string {
  if (!/&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);/i.test(value)) return value;
  const container = document.createElement("div");
  container.innerHTML = value;
  return container.textContent ?? value;
}

function HtmlBodyRenderer({ html }: { html: string }) {
  const sanitizedHtml = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["embed", "form", "iframe", "object", "script", "style"],
  });

  return (
    <div
      className="email-html-body max-w-none break-words text-[15px] leading-7 text-gray-800"
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
    />
  );
}

function EmailDetailView({ email }: EmailDetailViewProps) {
  const hasHtmlBody = Boolean(email.body_html);
  const hasTextBody = Boolean(email.body_text);

  return (
    <article className="bg-white rounded-xl shadow-md overflow-hidden">
      {/* Subject */}
      <div className="px-6 pt-6 pb-4 border-b border-gray-100">
        <h1 className="text-xl font-bold text-gray-900 leading-snug break-words">
          {email.subject ?? "(no subject)"}
        </h1>
        {email.snippet && (
          <p className="mt-1 text-sm text-gray-500 line-clamp-2">{email.snippet}</p>
        )}
      </div>

      {/* Header metadata */}
      <div className="px-6 py-4 border-b border-gray-100 space-y-3 text-sm">
        <div className="grid grid-cols-[4rem_minmax(0,1fr)] gap-x-3 gap-y-1">
          <span className="font-medium text-gray-500">From</span>
          <span className="text-gray-900 break-all">{email.sender}</span>
          <span className="font-medium text-gray-500">To</span>
          <span className="text-gray-900 break-all">
            {email.recipients.length > 0 ? email.recipients.join(", ") : "(none)"}
          </span>
          {email.cc.length > 0 && (
            <>
              <span className="font-medium text-gray-500">Cc</span>
              <span className="text-gray-900 break-all">{email.cc.join(", ")}</span>
            </>
          )}
          <span className="font-medium text-gray-500">Date</span>
          <time className="text-gray-900" dateTime={email.received_at}>{formatDate(email.received_at)}</time>
        </div>
      </div>

      {/* Attachments */}
      {email.has_attachments && email.attachments.length > 0 && (
        <div className="px-6 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">
            Attachments ({email.attachments.length})
          </h2>
          <div className="flex flex-wrap gap-2">
            {email.attachments.map((attachment) => (
              <div key={attachment.id} className="inline-flex items-center px-3 py-1.5 bg-gray-50 rounded-md text-sm">
                <svg className="w-4 h-4 mr-1.5 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                <span className="font-medium text-gray-700">{attachment.filename}</span>
                <span className="ml-2 text-gray-400">{formatSize(attachment.size)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Body */}
      <div className="px-6 py-5">
        {hasHtmlBody ? (
          <HtmlBodyRenderer html={email.body_html!} />
        ) : hasTextBody ? (
          <div
            className="text-gray-800 text-sm leading-relaxed max-w-none break-words"
            style={{ whiteSpace: "pre-wrap" }}
          >
            {decodeHtmlEntities(email.body_text!)}
          </div>
        ) : (
          <p className="text-gray-400 italic text-sm">(no body content)</p>
        )}
      </div>
    </article>
  );
}

export default EmailDetailView;