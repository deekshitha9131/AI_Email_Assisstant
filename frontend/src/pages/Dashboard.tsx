import { useNavigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { getServiceStatus } from "@/api";
import { loginUrl } from "@/api/auth";
import NotificationBell from "@/components/notifications/NotificationBell";
import type { AIStatus, AutomationStatusSnapshot } from "@/api/status";

type DashboardStatus = {
  gmail: "checking" | "connected" | "disconnected" | "expired" | "error";
  ai: "checking" | AIStatus | "error";
  draft: "checking" | "ready" | "not-ready" | "error";
  automation: "checking" | AutomationStatusSnapshot | "error";
  loading: boolean;
  error: string | null;
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function formatTimestamp(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function automationLabel(snapshot: AutomationStatusSnapshot): string {
  switch (snapshot.status) {
    case "ok":
      return "Healthy";
    case "degraded":
      return "Degraded";
    case "error":
      return "Error";
    default:
      return "Unknown";
  }
}

function automationColor(snapshot: AutomationStatusSnapshot): string {
  switch (snapshot.status) {
    case "ok":
      return "bg-green-500";
    case "degraded":
      return "bg-yellow-500";
    case "error":
      return "bg-red-500";
    default:
      return "bg-gray-400";
  }
}

/* ------------------------------------------------------------------ */
/*  Small reusable pieces                                             */
/* ------------------------------------------------------------------ */

function StatusDot({ color, pulse }: { color: string; pulse?: boolean }) {
  return (
    <span className="relative flex h-3 w-3 mr-3 shrink-0">
      {pulse && (
        <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${color} opacity-40`} />
      )}
      <span className={`relative inline-flex h-3 w-3 rounded-full ${color}`} />
    </span>
  );
}

function SectionCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 hover:shadow-md transition-shadow">
      <div className="flex items-center gap-2.5 mb-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
          {icon}
        </span>
        <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Dashboard                                                         */
/* ------------------------------------------------------------------ */

function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<DashboardStatus>({
    gmail: "checking",
    ai: "checking",
    draft: "checking",
    automation: "checking",
    loading: true,
    error: null as string | null,
  });

  const checkStatus = useCallback(async () => {
    setStatus(prev => ({ ...prev, loading: true, error: null }));

    try {
      // Get comprehensive status from backend
      const serviceStatus = await getServiceStatus();
      
      setStatus({
        gmail: serviceStatus.gmail,
        ai: serviceStatus.ai,
        draft: serviceStatus.draft,
        automation: serviceStatus.automation,
        loading: false,
        error: null,
      });
    } catch (error) {
      console.error("Status check failed:", error);
      setStatus(prev => ({
        ...prev,
        loading: false,
        error: "Failed to check service status. Please try again.",
        gmail: "error",
        ai: "error",
        draft: "error",
      }));
    }
  }, []);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  /* --- derived state for cleaner render --- */
  const isLoading = status.loading;
  const firstName = (user?.full_name ?? user?.email ?? "").split(/[\s@]/)[0];

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-blue-50/30">
      {/* ---- Header bar ---- */}
      <header className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="container flex items-center justify-between py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-sm shadow-sm">
              AI
            </span>
            <span className="text-lg font-semibold text-gray-900 hidden sm:inline">Email Assistant</span>
          </div>

          <div className="flex items-center gap-3">
            <NotificationBell />
            <button
              onClick={handleLogout}
              type="button"
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      <div className="container py-8 lg:py-10">
        {/* ---- Welcome banner ---- */}
        <div className="mb-8">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-1.5">
            Welcome back{firstName ? `, ${firstName}` : ""}!
          </h1>
          <p className="text-gray-500 text-sm sm:text-base">
            Your AI-powered email assistant is ready to help you manage your inbox.
          </p>
        </div>

        {/* ---- Error banner ---- */}
        {status.error && (
          <div className="mb-6 flex items-start gap-3 border-l-4 border-red-400 bg-red-50 rounded-r-lg p-4">
            <svg className="h-5 w-5 text-red-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <div>
              <p className="text-sm text-red-700">{status.error}</p>
              <button type="button" onClick={() => void checkStatus()} className="mt-2 text-sm font-medium text-red-800 hover:text-red-900 underline underline-offset-2">Retry</button>
            </div>
          </div>
        )}

        {/* ---- Cards grid ---- */}
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">

          {/* Account Status */}
          <SectionCard
            title="Account Status"
            icon={<svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>}
          >
            <div className="space-y-3">
              {/* Gmail */}
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <StatusDot
                    color={isLoading && status.gmail === "checking" ? "bg-gray-300" : status.gmail === "connected" ? "bg-green-500" : status.gmail === "disconnected" ? "bg-yellow-500" : "bg-red-500"}
                    pulse={isLoading && status.gmail === "checking"}
                  />
                  <span className="text-sm text-gray-700">
                    {isLoading && status.gmail === "checking" ? "Checking…" :
                     status.gmail === "connected" ? "Gmail Connected" :
                     status.gmail === "disconnected" ? "Gmail Disconnected" :
                     status.gmail === "expired" ? "Gmail Expired" :
                     "Gmail Error"}
                  </span>
                </div>
                {!isLoading && (status.gmail === "disconnected" || status.gmail === "expired") && (
                  <a
                    href={loginUrl}
                    className="rounded-md px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
                  >
                    {status.gmail === "disconnected" ? "Connect" : "Reconnect"}
                  </a>
                )}
              </div>

              {/* AI */}
              <div className="flex items-center">
                <StatusDot
                  color={isLoading && status.ai === "checking" ? "bg-gray-300" : status.ai === "available" ? "bg-green-500" : "bg-red-500"}
                  pulse={isLoading && status.ai === "checking"}
                />
                <span className="text-sm text-gray-700">
                  {isLoading && status.ai === "checking" ? "Checking…" :
                   status.ai === "available" ? "AI Available" :
                   status.ai === "not_configured" ? "AI Not Configured" :
                   status.ai === "authentication_error" ? "AI Auth Error" :
                   status.ai === "timeout" ? "AI Unavailable" :
                   "AI Error"}
                </span>
              </div>

              {/* Draft service */}
              <div className="flex items-center">
                <StatusDot
                  color={isLoading && status.draft === "checking" ? "bg-gray-300" : status.draft === "ready" ? "bg-green-500" : "bg-red-500"}
                  pulse={isLoading && status.draft === "checking"}
                />
                <span className="text-sm text-gray-700">
                  {isLoading && status.draft === "checking" ? "Checking…" :
                   status.draft === "ready" ? "Draft Service Ready" :
                   status.draft === "not-ready" ? "Draft Service Not Ready" :
                   "Draft Service Error"}
                </span>
              </div>
            </div>
          </SectionCard>

          {/* Automation Status */}
          <SectionCard
            title="Automation Status"
            icon={<svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>}
          >
            {status.automation === "checking" ? (
              <div className="flex items-center">
                <StatusDot color="bg-gray-300" pulse />
                <span className="text-sm text-gray-500">Checking…</span>
              </div>
            ) : typeof status.automation === "string" ? (
              <div className="flex items-center">
                <StatusDot color="bg-gray-400" />
                <span className="text-sm text-gray-500">Status unavailable</span>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center">
                  <StatusDot
                    color={automationColor(status.automation)}
                    pulse={status.automation.status === "ok"}
                  />
                  <span className="text-sm font-medium text-gray-800">
                    {automationLabel(status.automation)}
                  </span>
                </div>
                {status.automation.last_error != null && status.automation.last_error !== "" && status.automation.last_error !== "null" && (
                  <p className="text-xs text-red-600 bg-red-50 rounded-md px-3 py-2">
                    {status.automation.last_error}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-3 pt-1">
                  <div className="rounded-lg bg-gray-50 px-3 py-2">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">Last Success</p>
                    <p className="mt-0.5 text-xs text-gray-700">{formatTimestamp(status.automation.last_success_at)}</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">Last Failure</p>
                    <p className="mt-0.5 text-xs text-gray-700">{formatTimestamp(status.automation.last_failure_at)}</p>
                  </div>
                </div>
              </div>
            )}
          </SectionCard>

          {/* Quick Actions */}
          <SectionCard
            title="Quick Actions"
            icon={<svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>}
          >
            <div className="space-y-3">
              <button
                onClick={() => navigate("/inbox")}
                type="button"
                className="group w-full flex items-center justify-between px-4 py-3 bg-blue-50 hover:bg-blue-100 text-blue-800 font-medium rounded-lg transition-colors"
              >
                <span>Check Inbox</span>
                <svg className="w-4 h-4 text-blue-400 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                </svg>
              </button>
              <button
                onClick={() => navigate("/compose")}
                type="button"
                className="group w-full flex items-center justify-between px-4 py-3 bg-green-50 hover:bg-green-100 text-green-800 font-medium rounded-lg transition-colors"
              >
                <span>Compose Email</span>
                <svg className="w-4 h-4 text-green-400 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                </svg>
              </button>
              <button
                onClick={() => navigate("/drafts")}
                type="button"
                className="group w-full flex items-center justify-between px-4 py-3 bg-amber-50 hover:bg-amber-100 text-amber-800 font-medium rounded-lg transition-colors"
              >
                <span>Open Drafts</span>
                <svg className="w-4 h-4 text-amber-400 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          </SectionCard>

          {/* Features */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 hover:shadow-md transition-shadow md:col-span-2 lg:col-span-3">
            <div className="flex items-center gap-2.5 mb-5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" /></svg>
              </span>
              <h2 className="text-base font-semibold text-gray-900">Features</h2>
            </div>
            <div className="grid gap-5 sm:grid-cols-3">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50">
                  <svg className="w-4 h-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900 text-sm">Smart Email Analysis</h3>
                  <p className="text-sm text-gray-500 mt-0.5">
                    Automatically categorize, prioritize, and understand your emails with AI.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-green-50">
                  <svg className="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900 text-sm">AI-Powered Drafting</h3>
                  <p className="text-sm text-gray-500 mt-0.5">
                    Generate professional email replies that match your writing style.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-purple-50">
                  <svg className="w-4 h-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900 text-sm">Inbox Organization</h3>
                  <p className="text-sm text-gray-500 mt-0.5">
                    Keep your emails organized with smart labeling and threading.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
