import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "react-toastify";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";

export default function ProfilePage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("overview");
  const [stats, setStats] = useState({ total: 0, completed: 0, pending: 0 });

  const initials = useMemo(() => {
    const src = user?.name || user?.email || "P";
    return src.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  }, [user]);

  const loadStats = useCallback(async () => {
    if (!user?.id) return;
    try {
      const response = await getUserTransactions(user.id, 200);
      const txns = response.transactions || [];
      setStats({
        total: txns.length,
        completed: txns.filter((t) => (t.status || "").toUpperCase() === "COMPLETED").length,
        pending: txns.filter((t) => (t.status || "").toUpperCase() === "PENDING").length,
      });
    } catch {
      // silently handle
    }
  }, [user?.id]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const tabs = [
    { id: "overview", label: "Overview", icon: "user" },
    { id: "security", label: "Security", icon: "lock" },
    { id: "preferences", label: "Preferences", icon: "settings" },
  ];

  const tabIcons = {
    user: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
    lock: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>,
    settings: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  };

  return (
    <div className="stack-lg page-enter">
      <div className="page-header">
        <h2>Profile</h2>
        <p>Manage your account information and preferences.</p>
      </div>

      <div className="profile-layout">
        {/* Left sidebar */}
        <div className="profile-sidebar">
          <div className="card profile-user-card">
            <div className="profile-avatar">{initials}</div>
            <div className="profile-name">{user?.name || "Patient"}</div>
            <div className="profile-email">{user?.email || "No email"}</div>
          </div>

          <div className="card" style={{ padding: "0.5rem" }}>
            <nav className="profile-nav">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  className={`profile-nav-link ${activeTab === tab.id ? "active" : ""}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tabIcons[tab.icon]}
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>
        </div>

        {/* Right content */}
        <div className="profile-main">
          {activeTab === "overview" && (
            <>
              <div className="card profile-section-card">
                <h3>Personal Information</h3>
                <div className="profile-field">
                  <div className="profile-field-label">Full Name</div>
                  <div className="profile-field-value">{user?.name || "-"}</div>
                </div>
                <div className="profile-field">
                  <div className="profile-field-label">Email</div>
                  <div className="profile-field-value">{user?.email || "-"}</div>
                </div>
                <div className="profile-field">
                  <div className="profile-field-label">User ID</div>
                  <div className="profile-field-value" style={{ fontFamily: "monospace", fontSize: "0.82rem" }}>{user?.id || "-"}</div>
                </div>
              </div>

              <div className="card profile-section-card">
                <h3>Report Statistics</h3>
                <div className="stats-grid" style={{ marginTop: "0.5rem" }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "var(--text-primary)" }}>{stats.total}</div>
                    <div className="text-muted text-sm">Total Reports</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "var(--success)" }}>{stats.completed}</div>
                    <div className="text-muted text-sm">Completed</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "var(--warning)" }}>{stats.pending}</div>
                    <div className="text-muted text-sm">In Progress</div>
                  </div>
                </div>
              </div>
            </>
          )}

          {activeTab === "security" && (
            <div className="card profile-section-card">
              <h3>Security Settings</h3>
              <div className="profile-field">
                <div className="profile-field-label">Password</div>
                <div className="profile-field-value">
                  ••••••••
                  <p className="text-muted text-sm" style={{ marginTop: 4 }}>Password change functionality coming soon.</p>
                </div>
              </div>
              <div className="profile-field">
                <div className="profile-field-label">Sessions</div>
                <div className="profile-field-value">
                  <span className="badge badge-success">Active</span>
                  <p className="text-muted text-sm" style={{ marginTop: 4 }}>Your current session is active and secure.</p>
                </div>
              </div>
            </div>
          )}

          {activeTab === "preferences" && (
            <div className="card profile-section-card">
              <h3>Preferences</h3>
              <div className="profile-field">
                <div className="profile-field-label">Language</div>
                <div className="profile-field-value">English (default for voice generation)</div>
              </div>
              <div className="profile-field">
                <div className="profile-field-label">Notifications</div>
                <div className="profile-field-value">
                  <span className="badge badge-info">Enabled</span>
                  <p className="text-muted text-sm" style={{ marginTop: 4 }}>In-app toast notifications are enabled.</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
