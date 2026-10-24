import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "react-toastify";
import { useAuth } from "../hooks/useAuth";
import { extractPdfToStructuredData } from "../services/reportService";
import { createStoredRecord, deleteStoredRecord, getStoredRecords } from "../services/storedRecordService";
import { checkAbnormal } from "../utils/formatters";

export default function StorePage() {
  const { user } = useAuth();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [records, setRecords] = useState([]);
  const [previewRec, setPreviewRec] = useState(null);
  const [pdfViewRec, setPdfViewRec] = useState(null);
  const [researchingId, setResearchingId] = useState(null);

  const loadRecords = useCallback(async () => {
    if (!user?.id) return;
    try {
      setRecords(await getStoredRecords(user.id));
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Unable to load stored records.");
    }
  }, [user?.id]);

  useEffect(() => { loadRecords(); }, [loadRecords]);

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

  /* Build a flat parameter array from any backend response shape */
  const normalizeParameters = (data) => {
    const rows = [];

    // Array format (lab_parameters / parameters)
    const labParams = data.lab_parameters || data.parameters;
    if (Array.isArray(labParams) && labParams.length > 0) {
      labParams.forEach((p) =>
        rows.push({
          name: p.parameter_name || p.name || "Parameter",
          value: p.value ?? "-",
          unit: p.unit || "-",
          ref: p.bio_ref_range || p.reference_range || "-",
          date: p.date || data.reportDate || "-",
        })
      );
      return rows;
    }

    // Single primary parameter
    if (data.parameterName || data.currentValue) {
      rows.push({
        name: data.parameterName || "Primary Parameter",
        value: data.currentValue || "-",
        unit: "-",
        ref: "-",
        date: data.reportDate || "-",
      });
    }

    // linkedParameters object
    const linked = data.linkedParameters || {};
    Object.entries(linked).forEach(([key, param]) => {
      const vals = param?.currentValues || [];
      if (!vals.length) {
        rows.push({ name: param?.name || key, value: "-", unit: "-", ref: param?.normalRange || "-", date: data.reportDate || "-" });
        return;
      }
      vals.forEach((entry) =>
        rows.push({
          name: param?.name || key,
          value: entry?.value || "-",
          unit: entry?.unit || "-",
          ref: param?.normalRange || "-",
          date: entry?.date || data.reportDate || "-",
        })
      );
    });
    return rows;
  };

  const handleStore = useCallback(async () => {
    if (!file || !user?.id) return;
    setUploading(true);
    try {
      const data = await extractPdfToStructuredData(file, user.id);

      const parameters = normalizeParameters(data);

      const record = {
        id: crypto.randomUUID(),
        fileName: file.name,
        fileSize: file.size,
        storedAt: new Date().toISOString(),
        parameters,
        patientInfo: {
          ...(data.patient_info || data.patientInfo || {}),
          ...(data.age != null ? { age: data.age } : {}),
          ...(data.gender ? { gender: data.gender } : {}),
          ...(data.bmi != null ? { bmi: data.bmi } : {}),
        },
        chronicConditions: data.chronicCondition || data.chronicConditions || [],
        reportDate: data.reportDate || null,
        primaryParameter: data.parameterName || null,
        primaryValue: data.currentValue || null,
        language: data.language || "english",
        raw: data,
        deepResearchTxnId: null,
      };
      const savedRecord = await createStoredRecord(user.id, record);
      setRecords((current) => [savedRecord, ...current]);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      toast.success(`Report stored — ${parameters.length} parameters extracted!`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to extract report.");
    } finally {
      setUploading(false);
    }
  }, [file, user?.id]);

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

  const handleDelete = useCallback(async (id) => {
    try {
      await deleteStoredRecord(user.id, id);
      setRecords((current) => current.filter((record) => record.id !== id));
      toast.success("Record removed.");
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Could not remove record.");
    }
  }, [user?.id]);



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
          <div className="upload-progress-card">
            <div className="pulse-ring">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 28, height: 28 }}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <h3>Extracting Report...</h3>
            <p className="text-muted" style={{ marginTop: "0.5rem" }}>Running OCR and structuring your lab data.</p>
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
              <div key={rec.id} className="card record-card">
                <div className="record-card-header">
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                    <h4>{rec.fileName}</h4>
                    <span className="badge badge-info">Stored</span>
                  </div>
                </div>

                <div className="record-card-meta">
                  <span>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                    {rec.reportDate || new Date(rec.storedAt).toLocaleDateString()}
                  </span>
                  <span>{rec.parameters?.length || 0} parameters</span>
                  {rec.patientInfo?.age && <span>Age: {rec.patientInfo.age}</span>}
                  {rec.patientInfo?.gender && <span>{rec.patientInfo.gender}</span>}
                  {rec.patientInfo?.bmi != null && <span>BMI: {rec.patientInfo.bmi}</span>}
                  {rec.primaryParameter && (
                    <span style={{ color: "var(--accent)" }}>
                      Primary: {rec.primaryParameter} {rec.primaryValue ? `(${rec.primaryValue})` : ""}
                    </span>
                  )}
                  {rec.chronicConditions?.length > 0 && (
                    <span>Conditions: {rec.chronicConditions.join(", ")}</span>
                  )}
                </div>



                <div className="record-card-actions" style={{ marginTop: "0.75rem" }}>
                  <button className="btn btn-secondary btn-sm" onClick={() => setPreviewRec(rec)}>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14 }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    Extract &amp; Preview
                  </button>
                  {rec.pdfDataUrl && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setPdfViewRec(rec)}>
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14 }}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                      View PDF
                    </button>
                  )}
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

      {/* Extract & Preview Modal */}
      {previewRec && (
        <div className="modal-backdrop" onClick={() => setPreviewRec(null)} role="dialog" aria-modal="true">
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{previewRec.fileName} — Extracted Data</h3>
              <button className="modal-close-btn" onClick={() => setPreviewRec(null)} type="button" aria-label="Close">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="modal-body">
              {/* Patient info */}
              {previewRec.patientInfo && Object.keys(previewRec.patientInfo).length > 0 && (
                <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "var(--surface-alt)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: "0.5rem" }}>Patient Information</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.5rem" }}>
                    {Object.entries(previewRec.patientInfo).map(([key, val]) => (
                      val && (
                        <div key={key} style={{ fontSize: "0.85rem" }}>
                          <span style={{ color: "var(--text-muted)" }}>{key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}:</span>{" "}
                          <strong>{String(val)}</strong>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}

              {/* Parameters table */}
              {previewRec.parameters?.length > 0 ? (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Parameter</th>
                        <th>Value</th>
                        <th>Unit</th>
                        <th>Reference Range</th>
                        <th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewRec.parameters.map((p, i) => {
                        const refVal = p.ref || p.bio_ref_range || p.reference_range || "-";
                        const abnormal = checkAbnormal(p.value, refVal);
                        return (
                        <tr key={i} className={abnormal ? "param-abnormal" : ""}>
                          <td style={{ fontWeight: 600, color: abnormal ? "var(--danger)" : "var(--text-primary)" }}>
                            {p.name || p.parameter_name || "-"}
                            {abnormal && <span className="abnormal-badge">{abnormal === "high" ? "↑ HIGH" : "↓ LOW"}</span>}
                          </td>
                          <td><strong style={abnormal ? { color: "var(--danger)" } : undefined}>{p.value ?? "-"}</strong></td>
                          <td>{p.unit || "-"}</td>
                          <td>{refVal}</td>
                          <td className="text-muted">{p.date || "-"}</td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty-state" style={{ padding: "2rem" }}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  <h4>No Parameters Extracted</h4>
                  <p>The OCR could not extract structured lab parameters from this report.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* PDF Viewer Modal */}
      {pdfViewRec && (
        <div className="modal-backdrop" onClick={() => setPdfViewRec(null)} role="dialog" aria-modal="true">
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "900px", height: "85vh" }}>
            <div className="modal-header">
              <h3>{pdfViewRec.fileName}</h3>
              <button className="modal-close-btn" onClick={() => setPdfViewRec(null)} type="button" aria-label="Close">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="modal-body" style={{ padding: 0, flex: 1, overflow: "hidden" }}>
              <iframe
                src={pdfViewRec.pdfDataUrl}
                title={pdfViewRec.fileName}
                style={{ width: "100%", height: "100%", border: "none" }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
