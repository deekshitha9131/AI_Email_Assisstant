import { useCallback, useEffect, useState } from "react";

import { listEmails, searchEmails, type ListEmailsParams, type SearchEmailsParams } from "@/api/emails";
import type { EmailSummary } from "@/types";

type Status = "loading" | "success" | "error";

interface UseEmailsResult {
  status: Status;
  emails: EmailSummary[];
  page: number;
  pageSize: number;
  total: number;
  isEmpty: boolean;
  errorMessage: string | null;
  setPage: (page: number) => void;
  retry: () => void;
  refresh: () => void;
}

const PAGE_SIZE = 25;

interface UseEmailsParams extends Omit<ListEmailsParams, "page" | "page_size"> {
  search?: string;
}

export function useEmails(params: UseEmailsParams = {}): UseEmailsResult {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<Status>("loading");
  const [emails, setEmails] = useState<EmailSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const fetchEmails = useCallback(async () => {
    setStatus("loading");
    setErrorMessage(null);
    try {
      let result;
      // If search term is provided and not empty/whitespace, use search endpoint
      if (params.search && params.search.trim()) {
        const searchParams: SearchEmailsParams = {
          q: params.search,
          page,
          page_size: PAGE_SIZE,
        };
        result = await searchEmails(searchParams);
      } else {
        // Otherwise use regular list endpoint (also handles empty search)
        const listParams = { ...params };
        // Remove search param if it exists since listEmails doesn't accept it
        delete listParams.search;
        result = await listEmails({ ...listParams, page, page_size: PAGE_SIZE });
      }
      setEmails(result.items);
      setTotal(result.total);
      setStatus("success");
    } catch {
      // If search fails with validation error (empty query), fall back to regular list
      if (params.search && !params.search.trim()) {
        try {
          const listParams = { ...params };
          delete listParams.search;
          const result = await listEmails({ ...listParams, page, page_size: PAGE_SIZE });
          setEmails(result.items);
          setTotal(result.total);
          setStatus("success");
          return;
        } catch {
          setErrorMessage("We couldn't load your inbox. Please try again.");
          setStatus("error");
          return;
        }
      }
      setErrorMessage("We couldn't load your inbox. Please try again.");
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, params.search, reloadToken]);

  useEffect(() => {
    void fetchEmails();
  }, [fetchEmails]);

  const retry = useCallback(() => setReloadToken((token) => token + 1), []);

  return {
    status,
    emails,
    page,
    pageSize: PAGE_SIZE,
    total,
    isEmpty: status === "success" && emails.length === 0,
    errorMessage,
    setPage,
    retry,
    refresh: retry,
  };
}