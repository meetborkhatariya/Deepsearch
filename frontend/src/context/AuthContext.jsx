import { useCallback, useEffect, useMemo, useState } from "react";
import * as authService from "../services/authService";
import { AuthContext } from "./authContextObject";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    authService
      .getCurrentSession()
      .then((session) => {
        if (!mounted || !session) return;
        setUser(session.user || null);
        setToken(session.token || null);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(async (payload) => {
    const session = await authService.login(payload);
    setUser(session.user || null);
    setToken(session.token || null);
    return session;
  }, []);

  const signup = useCallback(async (payload) => {
    const session = await authService.signup(payload);
    setUser(session.user || null);
    setToken(session.token || null);
    return session;
  }, []);

  const logout = useCallback(async () => {
    await authService.logout();
    setUser(null);
    setToken(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      isAuthenticated: Boolean(user),
      login,
      signup,
      logout,
    }),
    [user, token, loading, login, signup, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
