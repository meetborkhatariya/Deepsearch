export function formatDate(isoLikeValue) {
  if (!isoLikeValue) return "-";
  const date = new Date(isoLikeValue);
  if (Number.isNaN(date.getTime())) return isoLikeValue;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatStatus(status) {
  if (!status) return "Unknown";
  return status.toLowerCase().replace(/(^\w|_\w)/g, (match) => match.replace("_", " ").toUpperCase());
}

/**
 * Parse a reference range string like "40 - 60", "< 200", "> 10",
 * "0.5-1.5", "Up to 200" and determine if a numeric value is abnormal.
 * Returns: "high" | "low" | null
 */
export function checkAbnormal(value, refRange) {
  if (!refRange || refRange === "-" || value == null || value === "-") return null;
  const num = parseFloat(String(value).replace(/[^0-9.]/g, ""));
  if (isNaN(num)) return null;

  const ref = String(refRange).trim();

  // Range: "40 - 60", "40-60", "40 to 60"
  const rangeMatch = ref.match(/^([<>]?\s*[\d.]+)\s*[-–—to]+\s*([<>]?\s*[\d.]+)/i);
  if (rangeMatch) {
    const lo = parseFloat(rangeMatch[1].replace(/[^0-9.]/g, ""));
    const hi = parseFloat(rangeMatch[2].replace(/[^0-9.]/g, ""));
    if (!isNaN(lo) && !isNaN(hi)) {
      if (num < lo) return "low";
      if (num > hi) return "high";
      return null;
    }
  }

  // Less than: "< 200", "Up to 200", "Below 200"
  const ltMatch = ref.match(/^(?:<|less\s+than|up\s+to|below)\s*([\d.]+)/i);
  if (ltMatch) {
    const hi = parseFloat(ltMatch[1]);
    if (!isNaN(hi) && num > hi) return "high";
    return null;
  }

  // Greater than: "> 10", "Above 10"
  const gtMatch = ref.match(/^(?:>|greater\s+than|above)\s*([\d.]+)/i);
  if (gtMatch) {
    const lo = parseFloat(gtMatch[1]);
    if (!isNaN(lo) && num < lo) return "low";
    return null;
  }

  return null;
}

export function toSafeArray(value) {
  if (Array.isArray(value)) return value;
  if (value == null) return [];
  return [value];
}
