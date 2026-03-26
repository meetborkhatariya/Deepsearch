import { formatDate, toSafeArray } from "../../utils/formatters";

function flattenStructuredData(analysis) {
  const rows = [];
  const structured = analysis?.structured_summary;

  if (Array.isArray(structured)) {
    structured.forEach((item, index) => {
      rows.push({
        id: `${item.parameterName || item.name || "param"}-${index}`,
        parameter: item.parameterName || item.name || "-",
        value: item.currentValue || item.value || "-",
        date: item.reportDate || item.date || analysis?.report_date || "-",
      });
    });
    return rows;
  }

  if (structured && typeof structured === "object") {
    const keys = Object.keys(structured);
    if (keys.length > 0) {
      keys.forEach((key, index) => {
        const value = structured[key];
        if (value && typeof value === "object") {
          const current = toSafeArray(value.currentValues)[0];
          rows.push({
            id: `${key}-${index}`,
            parameter: value.name || key,
            value: current?.value || value.currentValue || "-",
            date: current?.date || analysis?.report_date || "-",
          });
        }
      });
      return rows;
    }
  }

  if (analysis?.parameter_name || analysis?.parameterName) {
    rows.push({
      id: analysis.txn_id || analysis.reportId || "single-row",
      parameter: analysis.parameter_name || analysis.parameterName || "-",
      value: analysis.currentValue || "-",
      date: analysis.report_date || "-",
    });
  }

  return rows;
}

export default function HealthRecordsTable({ analyses }) {
  const rows = analyses.flatMap((analysis) => flattenStructuredData(analysis));

  if (!rows.length) {
    return (
      <div className="card muted-card">
        <h3>No structured health records yet</h3>
        <p>Upload a lab PDF to generate parameter history for this account.</p>
      </div>
    );
  }

  return (
    <div className="card table-card">
      <h3>Structured Health Data</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Parameter Name</th>
              <th>Value</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.parameter}</td>
                <td>{row.value}</td>
                <td>{formatDate(row.date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
