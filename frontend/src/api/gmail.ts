import { apiClient } from "./client";

export interface GmailSyncRequest {
  page_token?: string;
}

export interface GmailSyncResponse {
  success: boolean;
  threads_synced: number;
  emails_synced: number;
  attachments_found: number;
  emails_skipped: number;
  next_page_token?: string | null;
}

export interface GmailIncrementalSyncResponse {
  success: boolean;
  emails_synced: number;
  threads_updated: number;
  attachments_found: number;
  emails_skipped: number;
  history_id: string;
}

export interface GmailSendRequest {
  to: string[];
  subject: string;
  body_text?: string;
  body_html?: string;
  cc?: string[];
  bcc?: string[];
  thread_id?: string;
}

export interface GmailSendResponse {
  success: boolean;
  gmail_message_id: string;
  gmail_thread_id: string;
}

export async function gmailSync(
  params: GmailSyncRequest = {}
): Promise<GmailSyncResponse> {
  const response = await apiClient.post<GmailSyncResponse>("/gmail/sync", params);
  return response.data;
}

export async function gmailIncrementalSync(): Promise<GmailIncrementalSyncResponse> {
  const response = await apiClient.post<GmailIncrementalSyncResponse>("/gmail/sync/incremental");
  return response.data;
}

export async function gmailSend(
  data: GmailSendRequest
): Promise<GmailSendResponse> {
  const response = await apiClient.post<GmailSendResponse>("/gmail/send", data);
  return response.data;
}
