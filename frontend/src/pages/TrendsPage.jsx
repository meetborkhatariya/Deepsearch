import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "react-toastify";
import LoadingSpinner from "../components/common/LoadingSpinner";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { checkAbnormal, formatDate } from "../utils/formatters";

function numberValue(value) {
  const match = String(value ?? "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function addPoint(points, item, fallbackDate, fallbackName) {
  const value = numberValue(item?.value ?? item?.currentValue);
  if (value == null) return;
  points.push({
    value,
    label: item?.value ?? item?.currentValue,
    unit: item?.unit || "",
    date: item?.date || fallbackDate || "",
    ref: item?.bio_ref_range || item?.reference_range || item?.normalRange || "",
    name: item?.parameter_name || item?.parameterName || item?.name || fallbackName,
  });
}

function extractPoints(analysis) {
  const points = [];
  const structured = analysis?.structured_summary;
  const reportDate = analysis?.report_date || analysis?.started_at;

  if (Array.isArray(structured)) {
    structured.forEach((item) => {
      addPoint(points, item, reportDate, item?.parameterName || item?.name || "Parameter");
      (item?.previousValues || []).forEach((previous) => addPoint(points, previous, reportDate, item?.parameterName || item?.name));
    });
  } else if (structured && typeof structured === "object") {
    Object.entries(structured).forEach(([key, item]) => {
      if (!item || typeof item !== "object") return;
      const name = item.name || key;
      (item.currentValues || []).forEach((current) => addPoint(points, current, reportDate, name));
      addPoint(points, item, reportDate, name);
      (item.previousValues || []).forEach((previous) => addPoint(points, previous, reportDate, name));
    });
  }

  if (!points.length) {
    addPoint(points, {
      value: analysis?.currentValue,
      parameterName: analysis?.parameter_name,
      date: reportDate,
    }, reportDate, analysis?.parameter_name || "Parameter");
  }

  return points;
}

function TrendChart({ points }) {
  const width = 760;
  const height = 280;
  const padding = { top: 24, right: 24, bottom: 42, left: 48 };
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.1, 1);
  const lower = min - spread * 0.12;
  const upper = max + spread * 0.12;
  const x = (index) => padding.left + (index / Math.max(points.length - 1, 1)) * (width - padding.left - padding.right);
  const y = (value) => padding.top + ((upper - value) / (upper - lower)) * (height - padding.top - padding.bottom);
  const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");

  return (
    <div className="trend-chart-wrap">
      <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Health parameter trend chart">
        {[0, 1, 2, 3].map((step) => {
          const value = upper - ((upper - lower) * step) / 3;
          return <g key={step}><line className="trend-grid-line" x1={padding.left} x2={width - padding.right} y1={y(value)} y2={y(value)} /><text className="trend-axis-label" x={padding.left - 10} y={y(value) + 4} textAnchor="end">{value.toFixed(1)}</text></g>;
        })}
        <polyline className="trend-line" points={line} />
        {points.map((point, index) => <circle className="trend-point" key={`${point.date}-${index}`} cx={x(index)} cy={y(point.value)} r="5"><title>{`${point.label} ${point.unit} on ${formatDate(point.date)}`}</title></circle>)}
        {points.map((point, index) => <text className="trend-date-label" key={`date-${point.date}-${index}`} x={x(index)} y={height - 14} textAnchor="middle">{formatDate(point.date).replace(/\s+\d{4}$/, "")}</text>)}
      </svg>
    </div>
  );
}

export default function TrendsPage() {
  const { user } = useAuth();
  const [records, setRecords] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [loading, setLoading] = useState(true);

  const loadRecords = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const response = await getUserTransactions(user.id, 200);
      setRecords(response.transactions || []);
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Unable to load health trends.");
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => { loadRecords(); }, [loadRecords]);

  const allPoints = useMemo(() => records.flatMap(extractPoints), [records]);
  const parameterNames = useMemo(() => [...new Set(allPoints.map((point) => point.name).filter(Boolean))].sort(), [allPoints]);
  const activeName = selectedName || parameterNames[0] || "";
  const points = useMemo(() => allPoints.filter((point) => point.name === activeName).sort((a, b) => new Date(a.date) - new Date(b.date)), [activeName, allPoints]);
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];
  const direction = latest && previous ? latest.value > previous.value ? "Up" : latest.value < previous.value ? "Down" : "Stable" : "Baseline";
  const abnormal = latest ? checkAbnormal(latest.value, latest.ref) : null;

  if (loading) return <LoadingSpinner label="Loading health trends..." />;

  return (
    <div className="stack-lg page-enter">
      <div className="page-header">
        <h2>Health Trends</h2>
        <p>Follow how your reported health values change across time.</p>
      </div>

      {!parameterNames.length ? (
        <div className="card empty-state"><h3>Not enough structured data yet</h3><p>Upload lab reports with extracted values to see trends here.</p></div>
      ) : (
        <>
          <div className="card trend-controls">
            <label className="form-label" htmlFor="trend-parameter">Parameter</label>
            <select id="trend-parameter" className="form-select" value={activeName} onChange={(event) => setSelectedName(event.target.value)}>
              {parameterNames.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          <div className="stats-grid">
            <div className="card stat-card"><div className="stat-label">Latest value</div><div className="stat-value report-stat-value">{latest?.label} {latest?.unit}</div><div className="stat-subtext">{formatDate(latest?.date)}</div></div>
            <div className="card stat-card"><div className="stat-label">Direction</div><div className="stat-value report-stat-value">{direction}</div><div className="stat-subtext">Compared with the previous result</div></div>
            <div className="card stat-card"><div className="stat-label">Reference status</div><div className={`stat-value report-stat-value ${abnormal ? "trend-status-abnormal" : "trend-status-normal"}`}>{abnormal ? abnormal : "Within range"}</div><div className="stat-subtext">Based on the extracted reference range</div></div>
          </div>
          <section className="card trend-panel">
            <div className="card-header"><div><h3>{activeName}</h3><p className="text-muted text-sm">{points.length} recorded result{points.length === 1 ? "" : "s"}</p></div></div>
            {points.length > 1 ? <TrendChart points={points} /> : <div className="trend-empty"><p>A second result is needed to draw a trend line.</p><p className="text-muted text-sm">Your baseline value is still saved and will be compared automatically when a new report is uploaded.</p></div>}
          </section>
        </>
      )}
    </div>
  );
}