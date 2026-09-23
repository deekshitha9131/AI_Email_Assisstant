import DOMPurify from "dompurify";

/**
 * Decode HTML entities (e.g. &#x20; &amp; &lt;) to their character equivalents.
 */
export function decodeHtmlEntities(value: string): string {
  if (!/&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);/i.test(value)) return value;
  const container = document.createElement("div");
  container.innerHTML = DOMPurify.sanitize(value, { ALLOWED_TAGS: [] });
  return container.textContent ?? value;
}

/**
 * Convert raw URLs in plain-text into clickable &lt;a&gt; tags.
 * Keeps other text escaped to prevent injection.
 */
function linkify(text: string): string {
  const urlPattern = /(https?:\/\/[^\s<>"']+)/gi;
  return text.replace(urlPattern, (url) => {
    const safeUrl = DOMPurify.sanitize(url, { ALLOWED_TAGS: [] });
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-blue-700 underline underline-offset-2 break-all">${safeUrl}</a>`;
  });
}

/**
 * Renders sanitised HTML email body content.
 */
export function HtmlBodyRenderer({ html }: { html: string }) {
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

/**
 * Renders plain-text email body content with proper formatting:
 *  - HTML entities are decoded
 *  - Line breaks / paragraphs are preserved via white-space: pre-wrap
 *  - URLs become clickable links
 */
export function PlainTextBodyRenderer({ text }: { text: string }) {
  const decoded = decodeHtmlEntities(text);
  // Escape any remaining HTML so we can safely insert linkified content
  const escaped = decoded
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const linked = linkify(escaped);

  return (
    <div
      className="text-gray-800 text-sm leading-relaxed max-w-none break-words"
      style={{ whiteSpace: "pre-wrap" }}
      dangerouslySetInnerHTML={{ __html: linked }}
    />
  );
}

/**
 * Picks the best available body representation and renders it safely.
 */
export default function EmailBodyRenderer({
  bodyHtml,
  bodyText,
  fallback = "(No content)",
}: {
  bodyHtml?: string | null;
  bodyText?: string | null;
  fallback?: string;
}) {
  if (bodyHtml) return <HtmlBodyRenderer html={bodyHtml} />;
  if (bodyText) return <PlainTextBodyRenderer text={bodyText} />;
  return <p className="text-gray-400 italic text-sm">{fallback}</p>;
}
