import apiClient from "./apiClient";
import { clearAuthSession, getAuthSession, saveAuthSession } from "../utils/storage";

const LOGIN_ENDPOINT = import.meta.env.VITE_AUTH_LOGIN_ENDPOINT || "/api/v1/auth/login";
const SIGNUP_ENDPOINT = import.meta.env.VITE_AUTH_SIGNUP_ENDPOINT || "/api/v1/auth/signup";
const ME_ENDPOINT = import.meta.env.VITE_AUTH_ME_ENDPOINT || "/api/v1/auth/me";
const LOGOUT_ENDPOINT = import.meta.env.VITE_AUTH_LOGOUT_ENDPOINT || "/api/v1/auth/logout";
const ENABLE_LOCAL_FALLBACK = (import.meta.env.VITE_ENABLE_LOCAL_AUTH_FALLBACK || "false") === "true";

function buildUserFromEmail(email, name = "") {
  const id = email.split("@")[0].replace(/[^a-zA-Z0-9_-]/g, "").toLowerCase();
  return {
    id: id || "patient-user",
    name: name || "Patient",
    email,
  };
}

function normalizeAuthResponse(data, fallbackEmail = "", fallbackName = "") {
  const token = data?.access_token || data?.token || data?.jwt || null;
  const backendUser = data?.user || data?.data?.user || null;
  const user = backendUser
    ? {
        id: backendUser.id || backendUser.user_id || backendUser.email?.split("@")[0] || "patient-user",
        name: backendUser.name || backendUser.full_name || "Patient",
        email: backendUser.email || fallbackEmail,
      }
    : buildUserFromEmail(fallbackEmail, fallbackName);
  return { token, user };
}

function saveSession(session) {
  saveAuthSession(session);
  return session;
}

export async function login({ email, password }) {
  try {
    const { data } = await apiClient.post(LOGIN_ENDPOINT, { email, password });
    return saveSession(normalizeAuthResponse(data, email));
  } catch (error) {
    if (!ENABLE_LOCAL_FALLBACK) throw error;
    const fallback = { token: null, user: buildUserFromEmail(email) };
    return saveSession(fallback);
  }
}

export async function signup({ name, email, password }) {
  try {
    const { data } = await apiClient.post(SIGNUP_ENDPOINT, { name, email, password });
    return saveSession(normalizeAuthResponse(data, email, name));
  } catch (error) {
    if (!ENABLE_LOCAL_FALLBACK) throw error;
    const fallback = { token: null, user: buildUserFromEmail(email, name) };
    return saveSession(fallback);
  }
}

export async function getCurrentSession() {
  const localSession = getAuthSession();
  if (!localSession) return null;

  try {
    const { data } = await apiClient.get(ME_ENDPOINT);
    return saveSession(normalizeAuthResponse(data, localSession.user?.email, localSession.user?.name));
  } catch {
    return localSession;
  }
}

export async function logout() {
  try {
    await apiClient.post(LOGOUT_ENDPOINT);
  } catch {
    // Ignore logout endpoint failures to keep local session consistent.
  } finally {
    clearAuthSession();
  }
}
