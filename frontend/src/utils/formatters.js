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

export function toSafeArray(value) {
  if (Array.isArray(value)) return value;
  if (value == null) return [];
  return [value];
}
