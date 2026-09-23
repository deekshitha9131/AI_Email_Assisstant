import type { SentEmail } from "@/types";

import { apiClient } from "./client";

export interface ListSentEmailsParams {
  page_token?: string;
  page_size?: number;
}

export interface SentEmailsResponse {
  items: SentEmail[];
  next_page_token: string | null;
}

export async function listSentEmails(
  params: ListSentEmailsParams = {},
): Promise<SentEmailsResponse> {
  const response = await apiClient.get<SentEmailsResponse>("/gmail/sent", { params });
  return response.data;
}
