import { useCallback, useEffect, useState } from "react";
import { toast } from "react-toastify";
import HealthRecordsTable from "../components/records/HealthRecordsTable";
import LoadingSpinner from "../components/common/LoadingSpinner";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { formatDate, formatStatus } from "../utils/formatters";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";

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
      const message = error?.response?.data?.detail || "Could not load health records.";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) {
    return <LoadingSpinner label="Loading your records..." />;
  }

  const completedCount = analyses.filter((item) => (item.status || "").toUpperCase() === "COMPLETED").length;
  const pendingCount = analyses.filter((item) => (item.status || "").toUpperCase() === "PENDING").length;

  return (
    <section className="stack-xl page-enter">
      <div className="card hero-card dashboard-hero">
        <div>
          <h2>Welcome back, {user?.name || "Patient"}</h2>
          <p>Your health insights are organized here with trend-ready records and voice support.</p>
        </div>
        <button className="secondary-btn" onClick={loadDashboard}>Refresh Dashboard</button>
      </div>

      <div className="card-grid stats-grid">
        <article className="card stat-card">
          <h3>Total Reports</h3>
          <strong>{analyses.length}</strong>
        </article>
        <article className="card stat-card">
          <h3>Completed Analyses</h3>
          <strong>{completedCount}</strong>
        </article>
        <article className="card stat-card">
          <h3>In Progress</h3>
          <strong>{pendingCount}</strong>
        </article>
      </div>

      <div className="card-grid">
        {analyses.map((analysis) => (
          <article key={analysis.txn_id} className="card metric-card">
            <h3>{analysis.parameter_name || analysis.report_id || "Lab Report"}</h3>
            <p><strong>Status:</strong> {formatStatus(analysis.status)}</p>
            <p><strong>Date:</strong> {formatDate(analysis.report_date || analysis.started_at)}</p>
            {analysis.summary && <p className="line-clamp">{analysis.summary}</p>}
            <VoiceSummaryButton analysis={analysis} onVoiceGenerated={loadDashboard} />
          </article>
        ))}
      </div>

      <HealthRecordsTable analyses={analyses} />
    </section>
  );
}
