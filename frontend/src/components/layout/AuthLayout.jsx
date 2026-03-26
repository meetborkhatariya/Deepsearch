export default function AuthLayout({ title, subtitle, children, footerAction }) {
  return (
    <main className="auth-screen">
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-header">
            <div className="auth-logo">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            </div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>
          {children}
          {footerAction && <p className="auth-footer">{footerAction}</p>}
        </div>
      </div>
    </main>
  );
}
