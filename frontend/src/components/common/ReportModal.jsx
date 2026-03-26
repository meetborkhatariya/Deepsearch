import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ReportModal({ open, onClose, title, content }) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="Detailed report">
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{title || "Detailed Report"}</h3>
          <button className="ghost-btn" onClick={onClose} type="button">Close</button>
        </div>
        <div className="modal-body markdown-view">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || "No report content available."}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
