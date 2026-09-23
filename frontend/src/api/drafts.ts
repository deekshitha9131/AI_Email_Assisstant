import { apiClient } from "./client";
import type {
  Draft,
  DraftCreateRequest,
  DraftReviewListResponse,
  DraftUpdateRequest,
} from "@/types";

export async function listAIDrafts(): Promise<DraftReviewListResponse> {
  const response = await apiClient.get<DraftReviewListResponse>("/drafts");
  return response.data;
}

export async function createDraft(payload: DraftCreateRequest): Promise<Draft> {
  const response = await apiClient.post<Draft>("/drafts", payload);
  return response.data;
}

export async function getDraft(draftId: string): Promise<Draft> {
  const response = await apiClient.get<Draft>(`/drafts/${draftId}`);
  return response.data;
}


export async function updateDraft(draftId: string, payload: DraftUpdateRequest): Promise<Draft> {
  const response = await apiClient.patch<Draft>(`/drafts/${draftId}`, payload);
  return response.data;
}

export async function approveDraft(draftId: string): Promise<Draft> {
  const response = await apiClient.post<Draft>(`/drafts/${draftId}/approve`);
  return response.data;
}