import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "react-toastify";
import AuthLayout from "../components/layout/AuthLayout";
import { useAuth } from "../hooks/useAuth";
import { validateEmail } from "../utils/validators";

export default function LoginPage() {
  const [form, setForm] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
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
      title="Welcome back"
      subtitle="Sign in to securely manage your report analyses and health records."
      footerAction={
        <>
          New patient? <Link to="/signup">Create an account</Link>
        </>
      }
    >
      <form className="form-stack" onSubmit={onSubmit} noValidate>
        <label>
          Email
          <input
            type="email"
            name="email"
            value={form.email}
            onChange={onChange}
            placeholder="name@example.com"
            autoComplete="email"
            required
          />
          {errors.email && <span className="error-text">{errors.email}</span>}
        </label>
        <label>
          Password
          <input
            type="password"
            name="password"
            value={form.password}
            onChange={onChange}
            placeholder="Enter your password"
            autoComplete="current-password"
            required
          />
          {errors.password && <span className="error-text">{errors.password}</span>}
        </label>
        <button className="primary-btn" type="submit" disabled={submitting}>
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </AuthLayout>
  );
}
