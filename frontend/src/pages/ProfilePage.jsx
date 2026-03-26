import { useMemo } from "react";
import { useAuth } from "../hooks/useAuth";

export default function ProfilePage() {
  const { user } = useAuth();

  const initials = useMemo(() => {
    const source = user?.name || user?.email || "P";
    return source
      .split(" ")
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }, [user]);

  return (
    <section className="stack-xl page-enter">
      <div className="card profile-card">
        <div className="profile-avatar" aria-hidden="true">{initials}</div>
        <div className="profile-content">
          <h2>{user?.name || "Patient"}</h2>
          <p>{user?.email || "No email available"}</p>
          <div className="profile-tags">
            <span>Secure Account</span>
            <span>Report Insights Enabled</span>
            <span>Voice Summary Available</span>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Account Settings</h3>
        <p>
          This profile tab is ready for production extension: password reset, contact preferences,
          language defaults, and reminders can be added here without changing the main IA.
        </p>
      </div>
    </section>
  );
}
