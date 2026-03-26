import { useMemo } from "react";
import { formatDate, formatStatus } from "../../utils/formatters";

export default function PdfUploadCard({ statusData, previewData }) {
  const keyFacts = useMemo(() => {
    if (!previewData || typeof previewData !== "object") return [];
    return [
      { label: "Parameter", value: previewData.parameterName },
      { label: "Current Value", value: previewData.currentValue },
      { label: "Report Date", value: previewData.reportDate && formatDate(previewData.reportDate) },
      { label: "Model", value: previewData.model },
    ].filter((item) => item.value);
  }, [previewData]);

  return (
    <section className="upload-grid">
      <article className="card">
        <h3>Upload Status</h3>
        {!statusData ? (
          <p>Waiting for upload.</p>
        ) : (
          <div className="status-stack">
            <p><strong>Status:</strong> {formatStatus(statusData.status)}</p>
            {statusData.txn_id && <p><strong>Transaction ID:</strong> {statusData.txn_id}</p>}
            {statusData.reportId && <p><strong>Report ID:</strong> {statusData.reportId}</p>}
            {statusData.started_at && <p><strong>Started:</strong> {formatDate(statusData.started_at)}</p>}
            {statusData.completed_at && <p><strong>Completed:</strong> {formatDate(statusData.completed_at)}</p>}
            {statusData.message && <p>{statusData.message}</p>}
            {statusData.error && <p className="error-text">{statusData.error}</p>}
          </div>
        )}
      </article>
      <article className="card">
        <h3>Extracted Data Preview</h3>
        {!keyFacts.length ? (
          <p>Preview will appear after PDF extraction.</p>
        ) : (
          <ul className="facts-list">
            {keyFacts.map((item) => (
              <li key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  );
}
