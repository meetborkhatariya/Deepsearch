import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "react-toastify";
import { useAuth } from "../hooks/useAuth";
import { extractPdfToStructuredData, uploadPdfReport } from "../services/reportService";

const STORE_KEY_PREFIX = "health_stored_";

function getStoredRecords(userId) {
  try {
    const raw = localStorage.getItem(`${STORE_KEY_PREFIX}${userId}`);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveStoredRecords(userId, records) {
  localStorage.setItem(`${STORE_KEY_PREFIX}${userId}`, JSON.stringify(records));
}

export default function StorePage() {
  const { user } = useAuth();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [records, setRecords] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  const [researchingId, setResearchingId] = useState(null);

  useEffect(() => {
    if (user?.id) setRecords(getStoredRecords(user.id));
  }, [user?.id]);

  const handleFileChange = (e) => {
    const f = e.target.files?.[0];
    if (f && f.type === "application/pdf") setFile(f);
    else if (f) toast.error("Please select a PDF file.");
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f && f.type === "application/pdf") setFile(f);
    else toast.error("Please drop a PDF file.");
  };

  const handleStore = useCallback(async () => {
    if (!file || !user?.id) return;
    setUploading(true);
    try {
      const data = await extractPdfToStructuredData(file, user.id);
      const record = {
        id: crypto.randomUUID(),
        fileName: file.name,
        storedAt: new Date().toISOString(),
        parameters: data.lab_parameters || data.parameters || [],
        patientInfo: data.patient_info || data.patientInfo || {},
        raw: data,
        deepResearchTxnId: null,
      };
      const next = [record, ...records];
      setRecords(next);
      saveStoredRecords(user.id, next);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      toast.success("Report stored successfully!");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to extract report.");
    } finally {
      setUploading(false);
    }
  }, [file, user?.id, records]);

  const handleDeepResearch = useCallback(async (record) => {
    if (!user?.id) return;
    setResearchingId(record.id);
    try {
      // We need the original file to trigger deep research—re-upload from stored data
      // Since we don't have the file anymore, use the raw extracted data to call the lab_parameters endpoint
      // For simplicity, inform the user to re-upload through Deep Research page
      toast.info("To run deep research, please upload this report through the Deep Research page.");
    } catch {
      toast.error("Failed to trigger deep research.");
    } finally {
      setResearchingId(null);
    }
  }, [user?.id]);

  const handleDelete = useCallback((id) => {
    const next = records.filter((r) => r.id !== id);
    setRecords(next);
    if (user?.id) saveStoredRecords(user.id, next);
    toast.success("Record removed.");
  }, [records, user?.id]);

  const toggleExpand = (id) => setExpandedId(expandedId === id ? null : id);

  return (
    <div className="stack-lg page-enter">
      <div className="page-header">
        <h2>Store Records</h2>
        <p>Upload and store lab reports (OCR extraction only, no deep research).</p>
      </div>

      {/* Upload zone */}
      <div className="card">
        <div
          className="upload-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          role="button"
          tabIndex={0}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <p><strong>Click or drag</strong> a PDF lab report to store</p>
          <p className="text-muted text-sm">PDF files only</p>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            onChange={handleFileChange}
            hidden
          />
        </div>

        {file && (
          <div className="upload-file-info" style={{ marginTop: "1rem" }}>
            <div>
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span>{file.name}</span>
              <span className="text-muted text-sm">({(file.size / 1024).toFixed(1)} KB)</span>
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-ghost btn-sm" onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}>Cancel</button>
              <button className="btn btn-primary" onClick={handleStore} disabled={uploading}>
                {uploading ? <><span className="spinner spinner-sm" /> Extracting...</> : "Store Report"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Upload overlay */}
      {uploading && (
        <div className="upload-progress-overlay">
          <div className="upload-progress-content">
            <div className="upload-progress-ring" />
            <h3>Extracting Report...</h3>
            <p className="text-muted">Running OCR and structuring your lab data.</p>
          </div>
        </div>
      )}

      {/* Stored records */}
      <div className="stack">
        <div className="flex-between">
          <h3>Stored Records ({records.length})</h3>
        </div>

        {records.length === 0 ? (
          <div className="empty-state">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <h4>No Stored Records</h4>
            <p>Upload a lab report above to store and view structured data.</p>
          </div>
        ) : (
          <div className="records-list">
            {records.map((rec) => (
              <div key={rec.id} className="record-card">
                <div className="record-card-header">
                  <div>
                    <h4>{rec.fileName}</h4>
                    <span className="badge badge-info">Stored</span>
                  </div>
                </div>

                <div className="record-card-meta">
                  <span>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                    {new Date(rec.storedAt).toLocaleDateString()}
                  </span>
                  <span>{rec.parameters?.length || 0} parameters</span>
                </div>

                {/* Parameters table */}
                {rec.parameters?.length > 0 && (
                  <>
                    <button className="btn btn-ghost btn-sm" style={{ marginTop: "0.5rem" }} onClick={() => toggleExpand(rec.id)}>
                      {expandedId === rec.id ? "Hide Parameters" : "View Parameters"}
                    </button>

                    {expandedId === rec.id && (
                      <div className="table-container" style={{ marginTop: "0.5rem" }}>
                        <table>
                          <thead>
                            <tr>
                              <th>Parameter</th>
                              <th>Value</th>
                              <th>Unit</th>
                              <th>Reference</th>
                            </tr>
                          </thead>
                          <tbody>
                            {rec.parameters.map((p, i) => (
                              <tr key={i}>
                                <td>{p.parameter_name || p.name || "-"}</td>
                                <td><strong>{p.value ?? "-"}</strong></td>
                                <td>{p.unit || "-"}</td>
                                <td>{p.bio_ref_range || p.reference_range || "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}

                <div className="record-card-actions" style={{ marginTop: "0.75rem" }}>
                  <button className="btn btn-primary btn-sm" onClick={() => handleDeepResearch(rec)} disabled={researchingId === rec.id}>
                    {researchingId === rec.id ? <><span className="spinner spinner-sm" /> Running...</> : "Run Deep Research"}
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => handleDelete(rec.id)}>Remove</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
