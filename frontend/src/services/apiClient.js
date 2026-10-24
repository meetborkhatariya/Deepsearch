import axios from "axios";
import { getAuthSession } from "../utils/storage";

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  withCredentials: true,
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const session = getAuthSession();
  const token = session?.token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default apiClient;
