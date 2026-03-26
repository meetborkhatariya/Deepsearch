import { useCallback, useEffect, useState } from "react";
import { toast } from "react-toastify";
import LoadingSpinner from "../components/common/LoadingSpinner";
import HealthRecordsTable from "../components/records/HealthRecordsTable";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { formatDate, formatStatus } from "../utils/formatters";

export default function RecordsPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [records, setRecords] = useState([]);

  const loadRecords = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const response = await getUserTransactions(user.id, 100);
      setRecords(response.transactions || []);
    } catch (error) {
      const message = error?.response?.data?.detail || "Unable to load health records.";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  if (loading) {
    return <LoadingSpinner label="Loading your records..." />;
  }

  return (
    <section className="stack-xl page-enter">
      <div className="card hero-card records-hero">
        <div>
          <h2>Health Record Store</h2>
          <p>All your uploaded lab reports, deep research insights, and voice summaries in one place.</p>
        </div>
        <button className="secondary-btn" onClick={loadRecords}>Refresh Records</button>
      </div>

      <div className="record-list">
        {records.map((record) => (
          <article className="card record-item" key={record.txn_id}>
            <div className="record-head">
              <h3>{record.parameter_name || record.report_id || "Lab Report"}</h3>
              <span className={`status-pill status-${(record.status || "").toLowerCase()}`}>{formatStatus(record.status)}</span>
            </div>
            <p>{record.summary || "Summary will appear once analysis is complete."}</p>
            <div className="record-meta">
              <span>Report Date: {formatDate(record.report_date || record.started_at)}</span>
              <span>Completed: {formatDate(record.completed_at)}</span>
            </div>
            {record.full_analysis && <details><summary>View full deep research</summary><p>{record.full_analysis}</p></details>}
            <VoiceSummaryButton analysis={record} onVoiceGenerated={loadRecords} compact />
          </article>
        ))}
      </div>

      <HealthRecordsTable analyses={records} />
    </section>
  );
}
