import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ReportModal({ open, onClose, title, content }) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title || "Detailed Report"}</h3>
          <button className="modal-close-btn" onClick={onClose} type="button" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="modal-body markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content || "No report content available."}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
