import { API_BASE_URL, apiClient } from "./client";
import type { User } from "@/types";

export const loginUrl = `${API_BASE_URL}/auth/google/login`;

export async function getSession(): Promise<User> {
  const response = await apiClient.get<User>("/auth/session");
  return response.data;
}

export async function logout(): Promise<void> {
  await apiClient.post("/auth/logout");
}