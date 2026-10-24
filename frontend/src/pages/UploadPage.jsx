import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "react-toastify";
import ReportModal from "../components/common/ReportModal";
import { useAuth } from "../hooks/useAuth";
import { extractPdfToStructuredData, getReportStatus, uploadPdfReport } from "../services/reportService";
import { validatePdfFile } from "../utils/validators";
import { checkAbnormal } from "../utils/formatters";
import VoiceSummaryButton from "../components/records/VoiceSummaryButton";

const POLLING_INTERVAL_MS = 4500;

const RESEARCH_LANGUAGES = [
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "gujarati", label: "Gujarati" },
];

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [researchLanguage, setResearchLanguage] = useState("english");
  const { user } = useAuth();

  const userId = useMemo(() => user?.id || "guest-user", [user]);

  const previewRows = useMemo(() => {
    if (!previewData) return [];
    const rows = [];

    // Handle lab_parameters array format (from pdf_to_lab_json)
    const labParams = previewData.lab_parameters || previewData.parameters;
    if (Array.isArray(labParams) && labParams.length > 0) {
      labParams.forEach((p) => {
        rows.push({
          name: p.parameter_name || p.name || "Parameter",
          value: p.value ?? "-",
          unit: p.unit || "-",
          ref: p.bio_ref_range || p.reference_range || "-",
          date: p.date || previewData.reportDate || "-",
        });
      });
      return rows;
    }

    // Handle single parameter format
    if (previewData.parameterName || previewData.currentValue) {
      rows.push({
        name: previewData.parameterName || "Primary Parameter",
        value: previewData.currentValue || "-",
        unit: "-",
        ref: "-",
        date: previewData.reportDate || "-",
      });
    }

    // Handle linkedParameters object format
    const linked = previewData.linkedParameters || {};
    Object.entries(linked).forEach(([key, parameter]) => {
      const currentValues = parameter?.currentValues || [];
      if (!currentValues.length) {
        rows.push({ name: parameter?.name || key, value: "-", unit: "-", ref: "-", date: previewData.reportDate || "-" });
        return;
      }
      currentValues.forEach((entry) => {
        rows.push({
          name: parameter?.name || key,
          value: entry?.value || "-",
          unit: entry?.unit || "-",
          ref: parameter?.normalRange || "-",
          date: entry?.date || previewData.reportDate || "-",
        });
      });
    });
    return rows;
  }, [previewData]);

  // Step state
  const currentStep = useMemo(() => {
    if (analysisData) return 3;
    if (previewData || statusData) return 2;
    if (selectedFile) return 1;
    return 0;
  }, [selectedFile, previewData, statusData, analysisData]);

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
            toast.success("Your deep research report is ready!");
          }
          if (next.status === "FAILED") toast.error(next.error || "Report processing failed.");
        } catch {
          setPolling(false);
          toast.error("Could not fetch latest status.");
        }
      }, POLLING_INTERVAL_MS);
    }
    return () => { if (timer) clearTimeout(timer); };
  }, [polling, statusData]);

  const handleSelectFile = (event) => {
    const file = event.target.files?.[0];
    const err = validatePdfFile(file, 10);
    if (err) { toast.error(err); event.target.value = ""; return; }
    setSelectedFile(file);
    setPreviewData(null);
    setStatusData(null);
    setAnalysisData(null);
  };

  const handlePreview = async () => {
    if (!selectedFile) { toast.error("Choose a PDF file first."); return; }
    setExtracting(true);
    try {
      const extracted = await extractPdfToStructuredData(selectedFile, userId);
      setPreviewData(extracted);
      toast.info("Extraction preview ready.");
    } catch (error) {
      const detail = error?.response?.data?.detail;
      const status = error?.response?.status;
      if (detail) {
        toast.error(detail);
      } else if (error?.code === "ECONNABORTED") {
        toast.error("Extraction timed out — try a smaller PDF or check if the server is running.");
      } else if (!error?.response) {
        toast.error("Cannot reach the server. Please ensure the backend is running.");
      } else {
        toast.error(`Extraction failed (${status || "unknown error"}).`);
      }
      console.error("Preview extraction error:", error);
    } finally {
      setExtracting(false);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) { toast.error("Choose a PDF file first."); return; }
    setUploading(true);
    try {
      const response = await uploadPdfReport({ file: selectedFile, userId, language: researchLanguage });
      setStatusData(response);
      if (response.status === "PENDING") {
        setPolling(true);
        toast.success("Upload successful — deep research started.");
      } else {
        const hasReportText = response.summary || response.full_analysis;
        const completedReport = !hasReportText && response.txn_id
          ? await getReportStatus(response.txn_id)
          : response;
        setAnalysisData(completedReport);
        toast.success("Report processed.");
      }
    } catch (error) {
      const detail = error?.response?.data?.detail;
      if (detail) {
        toast.error(detail);
      } else if (error?.code === "ECONNABORTED") {
        toast.error("Upload is taking longer than expected. Keep this page open and check Records shortly.");
      } else if (!error?.response) {
        toast.error("Cannot reach the backend. Please check that the server is running.");
      } else {
        toast.error(`Upload failed (${error.response.status}).`);
      }
      console.error("Report upload error:", error);
    } finally {
      setUploading(false);
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPreviewData(null);
    setStatusData(null);
    setAnalysisData(null);
    setPolling(false);
    setDragOver(false);
  };

  const handleDragOver = useCallback((e) => { e.preventDefault(); setDragOver(true); }, []);
  const handleDragLeave = useCallback((e) => { e.preventDefault(); setDragOver(false); }, []);
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    const err = validatePdfFile(file, 10);
    if (err) { toast.error(err); return; }
    setSelectedFile(file);
    setPreviewData(null);
    setStatusData(null);
    setAnalysisData(null);
  }, []);

  const fileSizeKb = selectedFile ? (selectedFile.size / 1024).toFixed(1) : 0;
  const reportSummary = analysisData?.summary || analysisData?.full_analysis || "Report generated, but no report text was returned.";

  return (
    <div className="stack-lg page-enter">
      {/* Upload Progress Overlay */}
      {(uploading || polling) && (
        <div className="upload-progress-overlay">
          <div className="upload-progress-card">
            <div className="pulse-ring">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 28, height: 28 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <h3>{uploading ? "Uploading Report..." : "Analyzing with Deep Research"}</h3>
            <p style={{ marginTop: "0.5rem" }}>
              {uploading
                ? "Uploading and extracting parameters from your lab report."
                : "Our AI is performing deep research and web search to provide you with comprehensive, detailed health insights. This may take a few minutes — please be patient."}
            </p>
            <div className="progress-bar-track" style={{ marginTop: "1rem" }}>
              <div className="progress-bar-fill animated" style={{ width: uploading ? "40%" : "75%" }} />
            </div>
            {!uploading && (
              <p className="text-muted text-sm" style={{ marginTop: "0.75rem", fontStyle: "italic" }}>
                Analyzing parameters, searching medical databases, and generating your personalized report...
              </p>
            )}
          </div>
        </div>
      )}

      {/* Header */}
      <div className="page-header">
        <h2>Deep Research Analysis</h2>
        <p>Upload your lab report PDF to get AI-powered health insights with voice summary.</p>
      </div>

      {/* Progress Steps */}
      <div className="steps">
        <div className={`step ${currentStep >= 1 ? "active" : ""} ${currentStep > 1 ? "completed" : ""}`}>
          <span className="step-number">{currentStep > 1 ? "✓" : "1"}</span>
          Select File
        </div>
        <div className={`step-connector ${currentStep >= 2 ? "active" : ""}`} />
        <div className={`step ${currentStep >= 2 ? "active" : ""} ${currentStep > 2 ? "completed" : ""}`}>
          <span className="step-number">{currentStep > 2 ? "✓" : "2"}</span>
          Extract &amp; Preview
        </div>
        <div className={`step-connector ${currentStep >= 3 ? "active" : ""}`} />
        <div className={`step ${currentStep >= 3 ? "active" : ""}`}>
          <span className="step-number">3</span>
          Research Ready
        </div>
      </div>

      {/* Upload Zone */}
      <div className="card">
        <div className="card-header">
          <h3>Upload Lab Report</h3>
          {selectedFile && (
            <button className="btn btn-ghost btn-sm" onClick={handleReset}>Clear &amp; Reset</button>
          )}
        </div>

        {!selectedFile ? (
          <div
            className={`upload-zone ${dragOver ? "drag-over" : ""}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input type="file" accept="application/pdf,.pdf" onChange={handleSelectFile} aria-label="Upload medical report PDF" />
            <div className="upload-zone-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            </div>
            <h4>{dragOver ? "Drop your PDF here" : "Drop your PDF here or click to browse"}</h4>
            <p>Supports lab report PDFs up to 10 MB</p>
          </div>
        ) : (
          <div className="stack">
            <div className="upload-file-info">
              <div className="upload-file-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              </div>
              <div style={{ flex: 1 }}>
                <div className="upload-file-name">{selectedFile.name}</div>
                <div className="upload-file-size">{fileSizeKb} KB</div>
              </div>
              <span className="badge badge-success">Ready</span>
            </div>

            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "flex-end" }}>
              <button className="btn btn-secondary" onClick={handlePreview} disabled={extracting}>
                {extracting ? (
                  <><span className="spinner spinner-sm" style={{ display: "inline-block" }} /> Extracting...</>
                ) : (
                  <>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    Extract &amp; Preview
                  </>
                )}
              </button>
              <div className="language-select-wrap">
                <label htmlFor="research-lang" style={{ fontSize: "0.78rem" }}>Report Language:</label>
                <select
                  id="research-lang"
                  className="form-select"
                  value={researchLanguage}
                  onChange={(e) => setResearchLanguage(e.target.value)}
                  style={{ minWidth: 120, padding: "0.4rem 2rem 0.4rem 0.6rem", fontSize: "0.82rem" }}
                >
                  {RESEARCH_LANGUAGES.map((l) => (
                    <option key={l.value} value={l.value}>{l.label}</option>
                  ))}
                </select>
              </div>
              <button className="btn btn-primary" onClick={handleUpload} disabled={uploading}>
                {uploading ? (
                  <><span className="spinner spinner-sm" style={{ display: "inline-block" }} /> Uploading...</>
                ) : (
                  <>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Run Deep Research
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Extraction Preview */}
      {previewData && (
        <div className="card extraction-table-enter">
          <div className="card-header">
            <h3>Extracted Parameters</h3>
            <span className="badge badge-info">{previewRows.length} parameter{previewRows.length !== 1 ? "s" : ""} found</span>
          </div>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Value</th>
                  <th>Unit</th>
                  <th>Reference</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => {
                  const abnormal = checkAbnormal(row.value, row.ref);
                  return (
                  <tr key={`${row.name}-${i}`} className={abnormal ? "param-abnormal" : ""}>
                    <td style={{ fontWeight: 600, color: abnormal ? "var(--danger)" : "var(--text-primary)" }}>
                      {row.name}
                      {abnormal && <span className="abnormal-badge">{abnormal === "high" ? "↑ HIGH" : "↓ LOW"}</span>}
                    </td>
                    <td><strong style={abnormal ? { color: "var(--danger)" } : undefined}>{row.value}</strong></td>
                    <td>{row.unit}</td>
                    <td>{row.ref || "-"}</td>
                    <td>{row.date}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Analysis Results */}
      {analysisData && (
        <div className="card results-card analysis-reveal">
          <div className="card-header">
            <h3>Deep Research Results</h3>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-primary btn-sm" onClick={() => setShowReportModal(true)} type="button">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 15, height: 15 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                View Full Report
              </button>
            </div>
          </div>
          <p className="line-clamp-3" style={{ marginBottom: "1rem" }}>{reportSummary}</p>
          <VoiceSummaryButton analysis={analysisData} />
        </div>
      )}

      <ReportModal
        open={showReportModal}
        onClose={() => setShowReportModal(false)}
        title="Detailed Deep Research Report"
        content={analysisData?.full_analysis || analysisData?.summary}
      />
    </div>
  );
}
