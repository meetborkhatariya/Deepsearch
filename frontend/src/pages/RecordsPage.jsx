import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "react-toastify";
import LoadingSpinner from "../components/common/LoadingSpinner";
import ReportModal from "../components/common/ReportModal";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { formatDate, formatStatus } from "../utils/formatters";

export default function RecordsPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [records, setRecords] = useState([]);
  const [modalRecord, setModalRecord] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");

  const loadRecords = useCallback(async (showSpinner = true) => {
    if (!user?.id) return;
    if (showSpinner) setLoading(true);
    try {
      const response = await getUserTransactions(user.id, 100);
      setRecords(response.transactions || []);
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Unable to load health records.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  if (loading) return <LoadingSpinner label="Loading your records..." />;

  const statusBadge = (status) => {
    const s = (status || "").toUpperCase();
    if (s === "COMPLETED" || s === "SUCCESS") return "success";
    if (s === "FAILED") return "danger";
    return "warning";
  };

  const filteredRecords = records.filter((r) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (r.parameter_name || "").toLowerCase().includes(term)
      || (r.report_id || "").toLowerCase().includes(term)
      || (r.summary || "").toLowerCase().includes(term);
  });

  const completedCount = records.filter((r) => ["COMPLETED", "SUCCESS"].includes((r.status || "").toUpperCase())).length;

  return (
    <div className="stack-lg page-enter">
      <div className="flex-between">
        <div className="page-header" style={{ marginBottom: 0 }}>
          <h2>Health Records</h2>
          <p>All your uploaded lab reports and deep research insights in one place.</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={loadRecords}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 15, height: 15 }}><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Refresh
        </button>
      </div>

      {/* Stats bar + Search */}
      {records.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-md)", flexWrap: "wrap" }}>
          <div className="search-bar" style={{ flex: 1, minWidth: 200 }}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input
              type="text"
              placeholder="Search records..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div style={{ display: "flex", gap: "var(--space-sm)" }}>
            <span className="badge badge-info">{records.length} total</span>
            <span className="badge badge-success">{completedCount} completed</span>
          </div>
        </div>
      )}

      {records.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="empty-state-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <h3>No records yet</h3>
            <p>Upload your first lab report to start building your health record history.</p>
          </div>
        </div>
      ) : filteredRecords.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <h3>No matching records</h3>
            <p>Try a different search term.</p>
          </div>
        </div>
      ) : (
        <div className="records-list stagger-enter">
          {filteredRecords.map((record) => {
            const s = (record.status || "").toUpperCase();
            const isPending = s === "PENDING";
            return (
              <div className="card record-card" key={record.txn_id}>
                <div className="record-card-header">
                  <h3>{record.parameter_name || record.report_id || "Lab Report"}</h3>
                  <span className={`badge badge-${statusBadge(record.status)} ${isPending ? "badge-pulse" : ""}`}>
                    {isPending && <span className="status-dot status-dot-warning" />}
                    {formatStatus(record.status)}
                  </span>
                </div>

              {record.summary && (
                <p className="line-clamp-2">{record.summary}</p>
              )}

              <div className="record-card-meta">
                <span>
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  Report: {formatDate(record.report_date || record.started_at)}
                </span>
                {record.completed_at && (
                  <span>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    Completed: {formatDate(record.completed_at)}
                  </span>
                )}
              </div>

              <div className="record-card-actions">
                <Link className="btn btn-secondary btn-sm" to={`/records/${record.txn_id}`}>
                  View details
                </Link>
                {record.full_analysis && (
                  <button className="btn btn-secondary btn-sm" onClick={() => setModalRecord(record)}>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    View Full Report
                  </button>
                )}
              </div>

              <VoiceSummaryButton analysis={record} onVoiceGenerated={() => loadRecords(false)} />
            </div>
            );
          })}
        </div>
      )}

      <ReportModal
        open={!!modalRecord}
        onClose={() => setModalRecord(null)}
        title={modalRecord?.parameter_name || "Deep Research Report"}
        content={modalRecord?.full_analysis || modalRecord?.summary}
      />
    </div>
  );
}
