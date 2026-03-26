import { Link } from "react-router-dom";

export default function AuthLayout({ title, subtitle, children, footerAction }) {
  return (
    <main className="auth-screen">
      <section className="auth-card" aria-label="Authentication form">
        <div className="auth-brand-row">
          <div className="pulse-dot" aria-hidden="true" />
          <h1>Health Insight Portal</h1>
        </div>
        <p className="auth-subtitle">{subtitle}</p>
        <h2>{title}</h2>
        {children}
        <p className="auth-footer">{footerAction}</p>
        <p className="auth-note">
          Secure sign-in for report analysis and health records.
          <Link to="/signup"> Need an account?</Link>
        </p>
      </section>
    </main>
  );
}
