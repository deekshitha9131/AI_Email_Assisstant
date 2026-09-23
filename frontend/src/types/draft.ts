export type DraftStatus = "generated" | "approved" | "rejected" | "sent";

import type { EmailDetail } from "./email";

export interface Draft {
  id: string;
  email_id: string;
  body: string;
  status: DraftStatus;
  created_at: string;
  updated_at: string;
}

export interface DraftCreateRequest {
  email_id: string;
  instructions?: string | null;
}

export interface DraftUpdateRequest {
  body: string;
}

export interface ComposeDraft {
  id: string;
  user_id: string;
  recipients: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  body_text: string | null;
  body_html: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComposeDraftPayload {
  recipients: string[];
  cc?: string[];
  bcc?: string[];
  subject: string;
  body_text?: string | null;
  body_html?: string | null;
}

export interface ComposeDraftListResponse {
  items: ComposeDraft[];
  page: number;
  page_size: number;
}

export interface DraftReview extends Draft {
  email: EmailDetail;
}

export interface DraftReviewListResponse {
  items: DraftReview[];
  page: number;
  page_size: number;
}