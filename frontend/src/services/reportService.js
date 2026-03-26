import apiClient from "./apiClient";
import { saveTxnForUser } from "../utils/storage";

const PDF_TO_JSON_ENDPOINT = "/api/v1/pdf_to_lab_json";
const UPLOAD_REPORT_ENDPOINT = "/api/v1/upload_pdf_report";
const STATUS_ENDPOINT = "/api/v1/lab_parameters/status";

export async function extractPdfToStructuredData(file, userId) {
  const formData = new FormData();
  formData.append("file", file);
  if (userId) formData.append("user_id", userId);
  const { data } = await apiClient.post(PDF_TO_JSON_ENDPOINT, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function uploadPdfReport({ file, userId, language = "english", model = "openai" }) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("user_id", userId);
  formData.append("language", language);
  formData.append("model", model);

  const { data } = await apiClient.post(UPLOAD_REPORT_ENDPOINT, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  if (data?.txn_id && userId) {
    saveTxnForUser(userId, data.txn_id);
  }

  return data;
}

export async function getReportStatus(txnId) {
  const { data } = await apiClient.get(`${STATUS_ENDPOINT}/${txnId}`);
  return data;
}

export async function getUserTransactions(userId, limit = 100) {
  const { data } = await apiClient.get(`/api/v1/users/${userId}/transactions`, {
    params: { limit },
  });
  return data;
}

export async function checkVoiceEligibility(reportId, userId) {
  const { data } = await apiClient.post("/api/v1/report_check_for_voice", {
    report_id: reportId,
    user_id: userId,
  });
  return data;
}

export async function generateVoice({ reportId, userId, txnId, language }) {
  const payload = { user_id: userId };
  if (reportId) payload.report_id = reportId;
  if (txnId) payload.txn_id = txnId;
  if (language) payload.language = language;
  const { data } = await apiClient.post("/api/v1/generate_voice", payload);
  return data;
}
