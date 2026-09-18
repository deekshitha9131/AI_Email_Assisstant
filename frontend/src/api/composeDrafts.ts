import { apiClient } from "./client";
import type { ComposeDraft, ComposeDraftListResponse, ComposeDraftPayload } from "@/types";

export async function createComposeDraft(payload: ComposeDraftPayload): Promise<ComposeDraft> {
  const response = await apiClient.post<ComposeDraft>("/compose-drafts", payload);
  return response.data;
}

export async function listComposeDrafts(): Promise<ComposeDraftListResponse> {
  const response = await apiClient.get<ComposeDraftListResponse>("/compose-drafts");
  return response.data;
}

export async function getComposeDraft(draftId: string): Promise<ComposeDraft> {
  const response = await apiClient.get<ComposeDraft>(`/compose-drafts/${draftId}`);
  return response.data;
}

export async function updateComposeDraft(
  draftId: string,
  payload: ComposeDraftPayload,
): Promise<ComposeDraft> {
  const response = await apiClient.put<ComposeDraft>(`/compose-drafts/${draftId}`, payload);
  return response.data;
}

export async function deleteComposeDraft(draftId: string): Promise<void> {
  await apiClient.delete(`/compose-drafts/${draftId}`);
}