import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

export default function MainLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-line">
          <span className="pulse-dot" aria-hidden="true" />
          <strong>Health Insight Portal</strong>
        </div>
        <nav className="top-nav" aria-label="Primary">
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/records">Health Records</NavLink>
          <NavLink to="/upload">Upload Report</NavLink>
          <NavLink to="/profile">Profile</NavLink>
        </nav>
        <div className="user-zone">
          <span className="user-chip">{user?.name || "Patient"}</span>
          <button className="ghost-btn" onClick={handleLogout}>Sign out</button>
        </div>
      </header>
      <main className="page-shell">
        <Outlet />
      </main>
    </div>
  );
}
