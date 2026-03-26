import apiClient from "./apiClient";

export async function getHealthProfile(userId) {
  const { data } = await apiClient.get(`/api/v1/health-profile/${userId}`);
  return data;
}

export async function saveHealthProfile(userId, profile) {
  const { data } = await apiClient.put(`/api/v1/health-profile/${userId}`, profile);
  return data;
}
