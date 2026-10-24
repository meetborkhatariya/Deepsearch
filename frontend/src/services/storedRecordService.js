import apiClient from "./apiClient";

export async function getStoredRecords(userId) {
  const { data } = await apiClient.get(`/api/v1/users/${userId}/stored-records`);
  return data.records || [];
}

export async function createStoredRecord(userId, record) {
  const { data } = await apiClient.post(`/api/v1/users/${userId}/stored-records`, record);
  return data.record;
}

export async function deleteStoredRecord(userId, recordId) {
  await apiClient.delete(`/api/v1/users/${userId}/stored-records/${recordId}`);
}