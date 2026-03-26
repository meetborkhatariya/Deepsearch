import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "react-toastify";
import AuthLayout from "../components/layout/AuthLayout";
import { useAuth } from "../hooks/useAuth";
import {
  validateConfirmPassword,
  validateEmail,
  validateStrongPassword,
} from "../utils/validators";

export default function SignupPage() {
  const [form, setForm] = useState({ name: "", email: "", password: "", confirmPassword: "" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const { signup } = useAuth();
  const navigate = useNavigate();

  const onChange = (event) => {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const validate = () => {
    const nextErrors = {
      email: validateEmail(form.email),
      password: validateStrongPassword(form.password),
      confirmPassword: validateConfirmPassword(form.password, form.confirmPassword),
      name: form.name.trim() ? "" : "Name is required.",
    };
    setErrors(nextErrors);
    return Object.values(nextErrors).every((value) => !value);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!validate()) return;

    setSubmitting(true);
    try {
      await signup(form);
      toast.success("Account created successfully.");
      navigate("/dashboard", { replace: true });
    } catch (error) {
      const message = error?.response?.data?.detail || "Sign up failed. Please try again.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Set up secure access to upload reports and review your health trends."
      footerAction={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form className="form-stack" onSubmit={onSubmit} noValidate>
        <label>
          Full Name
          <input
            type="text"
            name="name"
            value={form.name}
            onChange={onChange}
            placeholder="Your name"
            autoComplete="name"
            required
          />
          {errors.name && <span className="error-text">{errors.name}</span>}
        </label>
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
            placeholder="Strong password"
            autoComplete="new-password"
            required
          />
          {errors.password && <span className="error-text">{errors.password}</span>}
        </label>
        <label>
          Confirm Password
          <input
            type="password"
            name="confirmPassword"
            value={form.confirmPassword}
            onChange={onChange}
            placeholder="Re-enter password"
            autoComplete="new-password"
            required
          />
          {errors.confirmPassword && <span className="error-text">{errors.confirmPassword}</span>}
        </label>
        <button className="primary-btn" type="submit" disabled={submitting}>
          {submitting ? "Creating account..." : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}
