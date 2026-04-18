import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "react-toastify";
import AuthLayout from "../components/layout/AuthLayout";
import { useAuth } from "../hooks/useAuth";
import { useLanguage } from "../context/LanguageContext";
import { validateEmail } from "../utils/validators";

export default function LoginPage() {
  const [form, setForm] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const { login } = useAuth();
  const { t, language, setLanguage, languages } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();

  const onChange = (event) => {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const validate = () => {
    const nextErrors = {
      email: validateEmail(form.email),
      password: form.password ? "" : "Password is required.",
    };
    setErrors(nextErrors);
    return !nextErrors.email && !nextErrors.password;
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!validate()) return;

    setSubmitting(true);
    try {
      await login(form);
      toast.success("Signed in successfully.");
      const fallbackPath = "/dashboard";
      const nextPath = location.state?.from?.pathname || fallbackPath;
      navigate(nextPath, { replace: true });
    } catch (error) {
      const message = error?.response?.data?.detail || "Login failed. Please try again.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title={t("welcome_back")}
      subtitle={t("sign_in_subtitle")}
      footerAction={
        <>
          {t("new_patient")} <Link to="/signup">{t("sign_up_link")}</Link>
        </>
      }
      languageSelector={
        <div className="auth-language-selector">
          <label className="form-label" style={{ marginBottom: 4, fontSize: "0.78rem" }}>{t("language")}</label>
          <div className="language-pills">
            {languages.map((lang) => (
              <button
                key={lang.value}
                type="button"
                className={`language-pill ${language === lang.value ? "active" : ""}`}
                onClick={() => setLanguage(lang.value)}
              >
                <span className="language-pill-flag">{lang.flag}</span>
                {lang.label}
              </button>
            ))}
          </div>
        </div>
      }
    >
      <form className="form-stack" onSubmit={onSubmit} noValidate>
        <div className="form-group">
          <label className="form-label">{t("email")}</label>
          <input
            className="form-input"
            type="email"
            name="email"
            value={form.email}
            onChange={onChange}
            placeholder="name@example.com"
            autoComplete="email"
            required
          />
          {errors.email && <span className="form-error">{errors.email}</span>}
        </div>
        <div className="form-group">
          <label className="form-label">{t("password")}</label>
          <div style={{ position: "relative" }}>
            <input
              className="form-input"
              type={showPassword ? "text" : "password"}
              name="password"
              value={form.password}
              onChange={onChange}
              placeholder="Enter your password"
              autoComplete="current-password"
              required
              style={{ paddingRight: "2.5rem" }}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              style={{
                position: "absolute", right: "0.6rem", top: "50%", transform: "translateY(-50%)",
                background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)",
                padding: "0.25rem", display: "grid", placeItems: "center"
              }}
              tabIndex={-1}
              aria-label={showPassword ? t("hide_password") : t("show_password")}
            >
              {showPassword ? (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 18, height: 18 }}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 18, height: 18 }}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              )}
            </button>
          </div>
          {errors.password && <span className="form-error">{errors.password}</span>}
        </div>
        <button className="btn btn-primary btn-lg" type="submit" disabled={submitting} style={{ width: "100%", marginTop: "0.5rem" }}>
          {submitting ? (
            <><span className="spinner spinner-sm" style={{ display: "inline-block" }} /> {t("signing_in")}</>
          ) : t("sign_in")}
        </button>
      </form>
    </AuthLayout>
  );
}
