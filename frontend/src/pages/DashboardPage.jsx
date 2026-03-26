import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "react-toastify";
import LoadingSpinner from "../components/common/LoadingSpinner";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { formatDate, formatStatus } from "../utils/formatters";

export default function DashboardPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [analyses, setAnalyses] = useState([]);

  const loadDashboard = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const response = await getUserTransactions(user.id, 50);
      setAnalyses(response.transactions || []);
    } catch (error) {
      const message = error?.response?.data?.detail || "Could not load dashboard data.";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) return <LoadingSpinner label="Loading dashboard..." />;

  const completedCount = analyses.filter((a) => (a.status || "").toUpperCase() === "COMPLETED").length;
  const pendingCount = analyses.filter((a) => (a.status || "").toUpperCase() === "PENDING").length;
  const recentAnalyses = analyses.slice(0, 5);

  return (
    <div className="stack-lg page-enter">
      {/* Welcome Banner */}
      <div className="welcome-banner">
        <h2>Welcome back, {user?.name || "Patient"}</h2>
        <p>Your health insights and report analysis overview.</p>
      </div>

      {/* Stats */}
      <div className="stats-grid stagger-enter">
        <div className="card stat-card">
          <div className="stat-icon stat-icon-blue">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <div className="stat-label">Total Reports</div>
          <div className="stat-value counter-value">{analyses.length}</div>
          <div className="stat-subtext">All uploaded reports</div>
        </div>
        <div className="card stat-card">
          <div className="stat-icon stat-icon-green">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          </div>
          <div className="stat-label">Completed</div>
          <div className="stat-value counter-value">{completedCount}</div>
          <div className="stat-subtext">Analysis ready</div>
        </div>
        <div className="card stat-card">
          <div className="stat-icon stat-icon-amber">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </div>
          <div className="stat-label">In Progress</div>
          <div className="stat-value counter-value">{pendingCount}</div>
          <div className="stat-subtext">{pendingCount > 0 ? "Processing now" : "All caught up"}</div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid-2">
        <Link to="/upload" className="quick-action-card">
          <div className="stat-icon stat-icon-blue" style={{ flexShrink: 0 }}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          </div>
          <div>
            <h3>Upload &amp; Analyze</h3>
            <p>Run deep research on a new lab report</p>
          </div>
        </Link>
        <Link to="/store" className="quick-action-card">
          <div className="stat-icon stat-icon-green" style={{ flexShrink: 0 }}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div>
            <h3>Store Report</h3>
            <p>Upload and save without deep research</p>
          </div>
        </Link>
      </div>

      {/* Recent Activity */}
      <div className="card">
        <div className="card-header">
          <h3>Recent Reports</h3>
          <Link to="/records" className="btn btn-ghost btn-sm">
            View all
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14 }}><polyline points="9 18 15 12 9 6"/></svg>
          </Link>
        </div>
        {recentAnalyses.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <h3>No reports yet</h3>
            <p>Upload your first lab report to get started with AI-powered health insights.</p>
            <Link to="/upload" className="btn btn-primary" style={{ marginTop: "1rem" }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              Upload Report
            </Link>
          </div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Report</th>
                  <th>Status</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {recentAnalyses.map((a) => {
                  const s = (a.status || "").toUpperCase();
                  const isPending = s === "PENDING";
                  return (
                    <tr key={a.txn_id}>
                      <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{a.parameter_name || a.report_id || "Lab Report"}</td>
                      <td>
                        <span className={`badge badge-${s === "COMPLETED" ? "success" : s === "FAILED" ? "danger" : "warning"} ${isPending ? "badge-pulse" : ""}`}>
                          {isPending && <span className="status-dot status-dot-warning" />}
                          {formatStatus(a.status)}
                        </span>
                      </td>
                      <td>{formatDate(a.report_date || a.started_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
