import axios from "axios";
import type { ApiErrorResponse } from "@/types";

export const API_BASE_URL = import.meta.env.PROD
  ? "/api/v1"
  : import.meta.env.VITE_API_BASE_URL;

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});


export class ApiError extends Error {
  code: string;
  requestId: string;
  status: number;
  fields?: ApiErrorResponse["error"]["fields"];

  constructor(status: number, body: ApiErrorResponse) {
    super(body.error.message);
    this.name = "ApiError";
    this.code = body.error.code;
    this.requestId = body.error.request_id;
    this.status = status;
    this.fields = body.error.fields;
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.data?.error) {
      throw new ApiError(error.response.status, error.response.data as ApiErrorResponse);
    }
    throw error;
  },
);