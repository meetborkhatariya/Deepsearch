import { useEffect, useMemo, useState } from "react";
import { toast } from "react-toastify";
import LoadingSpinner from "../components/common/LoadingSpinner";
import ReportModal from "../components/common/ReportModal";
import { useAuth } from "../hooks/useAuth";
import { extractPdfToStructuredData, getReportStatus, uploadPdfReport } from "../services/reportService";
import { validatePdfFile } from "../utils/validators";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";

const POLLING_INTERVAL_MS = 4500;

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const { user } = useAuth();

  const userId = useMemo(() => user?.id || "guest-user", [user]);
  const previewRows = useMemo(() => {
    if (!previewData) return [];
    const rows = [];
    if (previewData.parameterName || previewData.currentValue) {
      rows.push({
        name: previewData.parameterName || "Primary Parameter",
        value: previewData.currentValue || "-",
        unit: "-",
        date: previewData.reportDate || "-",
      });
    }

    const linked = previewData.linkedParameters || {};
    Object.entries(linked).forEach(([key, parameter]) => {
      const currentValues = parameter?.currentValues || [];
      if (!currentValues.length) {
        rows.push({
          name: parameter?.name || key,
          value: "-",
          unit: "-",
          date: previewData.reportDate || "-",
        });
        return;
      }
      currentValues.forEach((entry) => {
        rows.push({
          name: parameter?.name || key,
          value: entry?.value || "-",
          unit: entry?.unit || "-",
          date: entry?.date || previewData.reportDate || "-",
        });
      });
    });

    return rows;
  }, [previewData]);

  useEffect(() => {
    let timer;
    if (polling && statusData?.txn_id) {
      timer = setTimeout(async () => {
        try {
          const next = await getReportStatus(statusData.txn_id);
          setStatusData(next);
          if (next.status === "PENDING") return;
          setPolling(false);
          if (["SUCCESS", "COMPLETED"].includes((next.status || "").toUpperCase())) {
            setAnalysisData(next);
            toast.success("Your deep research report is ready.");
          }
          if (next.status === "FAILED") toast.error(next.error || "Report processing failed.");
        } catch {
          setPolling(false);
          toast.error("Could not fetch latest status.");
        }
      }, POLLING_INTERVAL_MS);
    }

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [polling, statusData]);

  const handleSelectFile = (event) => {
    const file = event.target.files?.[0];
    const validationError = validatePdfFile(file, 10);
    if (validationError) {
      toast.error(validationError);
      event.target.value = "";
      return;
    }
    setSelectedFile(file);
    setPreviewData(null);
    setStatusData(null);
    setAnalysisData(null);
  };

  const handlePreview = async () => {
    if (!selectedFile) {
      toast.error("Choose a PDF file first.");
      return;
    }

    setExtracting(true);
    try {
      const extracted = await extractPdfToStructuredData(selectedFile, userId);
      setPreviewData(extracted);
      toast.info("Extraction preview ready.");
    } catch (error) {
      const message = error?.response?.data?.detail || "Unable to extract PDF preview.";
      toast.error(message);
    } finally {
      setExtracting(false);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      toast.error("Choose a PDF file first.");
      return;
    }

    setUploading(true);
    try {
      const response = await uploadPdfReport({ file: selectedFile, userId });
      setStatusData(response);
      if (response.status === "PENDING") {
        setPolling(true);
        toast.success("Upload successful. Analysis started.");
      } else {
        setAnalysisData(response);
        toast.success("Report processed.");
      }
    } catch (error) {
      const message = error?.response?.data?.detail || "Upload failed.";
      toast.error(message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="stack-xl page-enter">
      <div className="card hero-card upload-hero">
        <div>
          <h2>Upload Your Lab Report</h2>
          <p>
            Get a clean deep research interpretation of your report with actionable insights and voice summary.
          </p>
        </div>
        <div className="step-row" role="status" aria-live="polite">
          <span className={`step-pill ${selectedFile ? "active" : ""}`}>1. File Selected</span>
          <span className={`step-pill ${previewData ? "active" : ""}`}>2. Extracted</span>
          <span className={`step-pill ${analysisData ? "active" : ""}`}>3. Deep Research Ready</span>
        </div>
        <div className="upload-actions upload-actions-modern">
          <label className="file-input-wrap">
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleSelectFile}
              aria-label="Upload medical report PDF"
            />
            <span>{selectedFile ? selectedFile.name : "Choose PDF report"}</span>
          </label>
          <button className="secondary-btn" onClick={handlePreview} disabled={extracting || !selectedFile}>
            {extracting ? "Extracting..." : "Preview Data"}
          </button>
          <button className="primary-btn" onClick={handleUpload} disabled={uploading || !selectedFile}>
            {uploading ? "Analyzing..." : "Run Deep Research"}
          </button>
        </div>
      </div>

      {(extracting || polling) && (
        <LoadingSpinner label={extracting ? "Extracting structured data from report..." : "Preparing your deep research analysis..."} />
      )}

      <div className="upload-grid">
        <article className="card">
          <h3>Extraction Preview</h3>
          {!previewData ? (
            <p>Parameter preview will appear here after extraction.</p>
          ) : (
            <>
              <p className="preview-caption">Detected {previewRows.length} parameter entr{previewRows.length === 1 ? "y" : "ies"} in this report.</p>
              <div className="table-wrap preview-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>Value</th>
                      <th>Unit</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows.map((row, index) => (
                      <tr key={`${row.name}-${index}`}>
                        <td>{row.name}</td>
                        <td>{row.value}</td>
                        <td>{row.unit}</td>
                        <td>{row.date}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </article>

        <article className="card">
          <h3>Analysis Status</h3>
          {!statusData ? (
            <p>No active analysis yet.</p>
          ) : (
            <>
              <p className="status-line">Current Status: <strong>{statusData.status || "PENDING"}</strong></p>
              <p>{statusData.message || "Your report is being processed."}</p>
              {statusData.error && <p className="error-text">{statusData.error}</p>}
            </>
          )}
        </article>
      </div>

      {analysisData?.summary && (
        <>
          <article className="card research-card">
            <div className="research-head">
              <h3>Deep Research Summary</h3>
              <div className="research-actions">
                <button className="secondary-btn" onClick={() => setShowReportModal(true)} type="button">Open Full Report</button>
                <VoiceSummaryButton analysis={analysisData} />
              </div>
            </div>
            <p>{analysisData.summary}</p>
          </article>
        </>
      )}

      <ReportModal
        open={showReportModal}
        onClose={() => setShowReportModal(false)}
        title="Detailed Deep Research Report"
        content={analysisData?.full_analysis || analysisData?.summary}
      />
    </section>
  );
}
