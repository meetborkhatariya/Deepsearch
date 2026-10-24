import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "react-toastify";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import LoadingSpinner from "../components/common/LoadingSpinner";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { formatDate, formatStatus } from "../utils/formatters";

function statusBadge(status) {
  const normalized = (status || "").toUpperCase();
  if (["COMPLETED", "SUCCESS"].includes(normalized)) return "success";
  if (normalized === "FAILED") return "danger";
  return "warning";
}

export default function ReportDetailPage() {
  const { txnId } = useParams();
  const { user } = useAuth();
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadReport = useCallback(async () => {
    if (!user?.id || !txnId) return;
    setLoading(true);
    try {
      const response = await getUserTransactions(user.id, 200);
      const match = (response.transactions || []).find((item) => item.txn_id === txnId);
      if (!match) {
        toast.error("Report not found.");
        return;
      }
      setRecord(match);
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Unable to load this report.");
    } finally {
      setLoading(false);
    }
  }, [txnId, user?.id]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  if (loading) return <LoadingSpinner label="Loading report details..." />;

  if (!record) {
    return (
      <div className="card empty-state page-enter">
        <h2>Report unavailable</h2>
        <p>This report may have been removed or you may not have access to it.</p>
        <Link className="btn btn-primary" to="/records">Back to records</Link>
      </div>
    );
  }

  const normalizedStatus = (record.status || "").toUpperCase();
  const reportText = record.full_analysis || record.summary;

  return (
    <div className="stack-lg page-enter">
      <div className="flex-between report-detail-header">
        <div className="page-header" style={{ marginBottom: 0 }}>
          <Link to="/records" className="btn btn-ghost btn-sm">Back to records</Link>
          <h2>{record.parameter_name || record.report_id || "Lab Report"}</h2>
          <p>Detailed analysis and processing information for this report.</p>
        </div>
        <span className={`badge badge-${statusBadge(record.status)}`}>
          {formatStatus(record.status)}
        </span>
      </div>

      <div className="stats-grid">
        <div className="card stat-card">
          <div className="stat-label">Report date</div>
          <div className="stat-value report-stat-value">{formatDate(record.report_date || record.started_at)}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Completed</div>
          <div className="stat-value report-stat-value">{formatDate(record.completed_at) || "In progress"}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Language</div>
          <div className="stat-value report-stat-value">{record.language || "English"}</div>
        </div>
      </div>

      {record.summary && (
        <section className="card report-detail-section">
          <div className="card-header"><h3>Key summary</h3></div>
          <p className="report-summary">{record.summary}</p>
        </section>
      )}

      <section className="card report-detail-section">
        <div className="card-header">
          <h3>Full analysis</h3>
          <span className="text-muted text-sm">Transaction {record.txn_id}</span>
        </div>
        {reportText ? (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportText}</ReactMarkdown>
          </div>
        ) : (
          <div className="empty-state"><p>Full analysis is not available yet.</p></div>
        )}
      </section>

      {normalizedStatus === "COMPLETED" && (
        <section className="card report-detail-section">
          <div className="card-header"><h3>Listen to this report</h3></div>
          <VoiceSummaryButton analysis={record} onVoiceGenerated={loadReport} />
        </section>
      )}
    </div>
  );
}