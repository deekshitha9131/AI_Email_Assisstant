import { apiClient } from "./client";

export interface ServiceStatus {
  gmail: "connected" | "disconnected" | "expired" | "error";
  ai: AIStatus;
  draft: "ready" | "not-ready" | "error";
  user: {
    id: string;
    email: string;
    full_name: string;
  } | null;
}

export type AIStatus =
  | "available"
  | "not_configured"
  | "authentication_error"
  | "provider_error"
  | "timeout";

export async function getServiceStatus(): Promise<ServiceStatus> {
  const response = await apiClient.get<ServiceStatus>("/status");
  return response.data;
}

export async function getGmailStatus(): Promise<{
  status: "connected" | "disconnected" | "expired";
}> {
  const response = await apiClient.get<{
    status: "connected" | "disconnected" | "expired";
  }>("/status/gmail");
  return response.data;
}

export async function getAIStatus(): Promise<{ status: AIStatus; provider?: string; model?: string }> {
  const response = await apiClient.get<{ status: AIStatus; provider?: string; model?: string }>("/status/ai");
  return response.data;
}

export async function getDraftStatus(): Promise<{ status: "ready" | "not-ready" | "error" }> {
  const response = await apiClient.get<{ status: "ready" | "not-ready" | "error" }>("/status/draft");
  return response.data;
}
