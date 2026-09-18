import { useNavigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { getServiceStatus } from "@/api";
import { loginUrl } from "@/api/auth";
import type { AIStatus } from "@/api/status";

type DashboardStatus = {
  gmail: "checking" | "connected" | "disconnected" | "expired" | "error";
  ai: "checking" | AIStatus | "error";
  draft: "checking" | "ready" | "not-ready" | "error";
  loading: boolean;
  error: string | null;
};

function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<DashboardStatus>({
    gmail: "checking",
    ai: "checking",
    draft: "checking",
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

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">
            Welcome back, {user?.full_name ?? user?.email}!
          </h1>
          <p className="text-gray-600">
            Your AI-powered email assistant is ready to help you manage your inbox.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {/* Status Card */}
          <div className="bg-white rounded-xl shadow-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Account Status</h2>
            <div className="space-y-3">
              <div className="flex items-center">
                <div
                  className={`w-3 h-3 ${status.loading && status.gmail === "checking" ? "bg-gray-300" : status.gmail === "connected" ? "bg-green-500" : status.gmail === "disconnected" ? "bg-yellow-500" : "bg-red-500"} rounded-full mr-3`}
                >
                </div>
                <span className="text-sm text-gray-600">
                  {status.loading && status.gmail === "checking" ? "Checking..." : 
                   status.gmail === "connected" ? "Connected to Gmail" :
                   status.gmail === "disconnected" ? "Gmail Disconnected" :
                   status.gmail === "expired" ? "Gmail Connection Expired" :
                   "Gmail Error"}
                </span>
                {!status.loading && (status.gmail === "disconnected" || status.gmail === "expired") && (
                  <button
                    type="button"
                    onClick={() => { window.location.href = loginUrl; }}
                    className="mt-2 px-3 py-1 bg-blue-50 hover:bg-blue-100 text-blue-800 font-sm rounded-md"
                  >
                    {status.gmail === "disconnected" ? "Connect Gmail" : "Reconnect Gmail"}
                  </button>
                )}
              </div>
              <div className="flex items-center">
                <div
                  className={`w-3 h-3 ${status.loading && status.ai === "checking" ? "bg-gray-300" : status.ai === "available" ? "bg-green-500" : "bg-red-500"} rounded-full mr-3`}
                >
                </div>
                <span className="text-sm text-gray-600">
                  {status.loading && status.ai === "checking" ? "Checking..." : 
                   status.ai === "available" ? "AI Available" :
                   status.ai === "not_configured" ? "AI Not Configured" :
                   status.ai === "authentication_error" ? "AI Authentication Error" :
                   status.ai === "timeout" ? "AI Temporarily Unavailable" :
                   "AI Service Error"}
                </span>
              </div>
              <div className="flex items-center">
                <div
                  className={`w-3 h-3 ${status.loading && status.draft === "checking" ? "bg-gray-300" : status.draft === "ready" ? "bg-green-500" : "bg-red-500"} rounded-full mr-3`}
                >
                </div>
                <span className="text-sm text-gray-600">
                  {status.loading && status.draft === "checking" ? "Checking..." : 
                   status.draft === "ready" ? "Draft Service Ready" :
                   status.draft === "not-ready" ? "Draft Service Not Ready" :
                   "Draft Service Error"}
                </span>
              </div>
            </div>
          </div>

          {/* Quick Actions Card */}
          <div className="bg-white rounded-xl shadow-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Actions</h2>
            <div className="space-y-4">
              <button
                onClick={() => navigate("/inbox")}
                type="button"
                className="w-full flex items-center justify-between px-4 py-3 bg-blue-50 hover:bg-blue-100 text-blue-800 font-medium rounded-lg transition-colors"
              >
                <span>Check Inbox</span>
                <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                </svg>
              </button>
              <button
                onClick={() => navigate("/compose")}
                type="button"
                className="w-full flex items-center justify-between px-4 py-3 bg-green-50 hover:bg-green-100 text-green-800 font-medium rounded-lg transition-colors"
              >
                <span>Compose Email</span>
                <svg className="w-4 h-4 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                </svg>
              </button>
              <button
                onClick={() => navigate("/drafts")}
                type="button"
                className="w-full flex items-center justify-between px-4 py-3 bg-yellow-50 hover:bg-yellow-100 text-yellow-800 font-medium rounded-lg transition-colors"
              >
                <span>Open Drafts</span>
                <svg className="w-4 h-4 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          </div>

          {/* Features Card */}
          <div className="bg-white rounded-xl shadow-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Features</h2>
            <div className="space-y-3">
              <div className="flex items-start">
                <div className="flex-shrink-0">
                  <svg className="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v2H5a2 2 0 00-2 2v2a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414l2-2a1 1 0 001.414-1.414V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="font-medium text-gray-900">Smart Email Analysis</h3>
                  <p className="text-sm text-gray-500">
                    Automatically categorize, prioritize, and understand your emails with AI.
                  </p>
                </div>
              </div>
              <div className="flex items-start">
                <div className="flex-shrink-0">
                  <svg className="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.218 2.944c.471 1.137-1.03 1.944-2.076 1.465l-3.323-1.576a1 1 0 00-1.153-.89l-3.323 1.576a1 1 0 00-2.076 1.465l1.218-2.944a1 1 0 00-.363-1.118l-3.976-2.888a1 1 0 00.588-1.81h4.915a1 1 0 00.95-.69l1.519-4.674z" />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="font-medium text-gray-900">AI-Powered Drafting</h3>
                  <p className="text-sm text-gray-500">
                    Generate professional email replies that match your writing style.
                  </p>
                </div>
              </div>
              <div className="flex items-start">
                <div className="flex-shrink-0">
                  <svg className="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000-16 1 1 0 00-2 0v2h2V6a2 2 0 104 0v2h2V4a2 2 0 104 0v2h2V2a2 2 0 104 0v2h2V0a1 1 0 100 2v2H2v2a2 2 0 00-2 2H0z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="font-medium text-gray-900">Inbox Organization</h3>
                  <p className="text-sm text-gray-500">
                    Keep your emails organized with smart labeling and threading.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-8">
          <button
            onClick={handleLogout}
            type="button"
            className="w-full px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium rounded-lg transition-colors"
          >
            Log out
          </button>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
