import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "react-toastify";
import { useAuth } from "../hooks/useAuth";
import { getUserTransactions } from "../services/reportService";
import { getHealthProfile, saveHealthProfile } from "../services/healthProfileService";

const GENDER_OPTIONS = ["Male", "Female", "Other", "Prefer not to say"];
const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Unknown"];
const YES_NO = ["No", "Yes"];
const DIET_TYPES = ["Vegetarian", "Non-Vegetarian", "Eggetarian", "Vegan"];
const SMOKING_OPTIONS = ["No", "Occasionally", "Yes"];
const ALCOHOL_OPTIONS = ["No", "Occasionally", "Yes"];

const EMPTY_PROFILE = {
  height_cm: "",
  weight_kg: "",
  age: "",
  gender: "",
  health_goal: "",
  blood_group: "",
  allergies: "",
  chronic_conditions: "",
  smoking: "No",
  alcohol: "No",
  diet_type: "Non-Vegetarian",
  health_history: "",
  surgeries: "",
};

export default function ProfilePage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("overview");
  const [stats, setStats] = useState({ total: 0, completed: 0, pending: 0 });

  // Health profile state
  const [profile, setProfile] = useState(EMPTY_PROFILE);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

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
      /* silent */
    }
  }, [user?.id]);

  const loadProfile = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await getHealthProfile(user.id);
      if (res.profile) {
        setProfile({
          height_cm: res.profile.height_cm ?? "",
          weight_kg: res.profile.weight_kg ?? "",
          age: res.profile.age ?? "",
          gender: res.profile.gender ?? "",
          health_goal: res.profile.health_goal ?? "",
          blood_group: res.profile.blood_group ?? "",
          allergies: res.profile.allergies ?? "",
          chronic_conditions: res.profile.chronic_conditions ?? "",
          smoking: res.profile.smoking ?? "No",
          alcohol: res.profile.alcohol ?? "No",
          diet_type: res.profile.diet_type ?? "Non-Vegetarian",
          health_history: res.profile.health_history ?? "",
          surgeries: res.profile.surgeries ?? "",
        });
      }
    } catch {
      /* first visit */
    } finally {
      setProfileLoaded(true);
    }
  }, [user?.id]);

  useEffect(() => {
    loadStats();
    loadProfile();
  }, [loadStats, loadProfile]);

  const handleProfileChange = (field, value) => {
    setProfile((p) => ({ ...p, [field]: value }));
    if (!editing) setEditing(true);
  };

  const handleSaveProfile = async () => {
    if (!user?.id) return;
    setSaving(true);
    try {
      const payload = {
        ...profile,
        height_cm: profile.height_cm ? Number(profile.height_cm) : null,
        weight_kg: profile.weight_kg ? Number(profile.weight_kg) : null,
        age: profile.age ? Number(profile.age) : null,
        gender: profile.gender || null,
        health_goal: profile.health_goal || null,
        blood_group: profile.blood_group || null,
        allergies: profile.allergies || null,
        chronic_conditions: profile.chronic_conditions || null,
        smoking: profile.smoking || null,
        alcohol: profile.alcohol || null,
        diet_type: profile.diet_type || null,
        health_history: profile.health_history || null,
        surgeries: profile.surgeries || null,
      };
      await saveHealthProfile(user.id, payload);
      toast.success("Health profile saved!");
      setEditing(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save profile.");
    } finally {
      setSaving(false);
    }
  };

  const bmi = useMemo(() => {
    const h = Number(profile.height_cm);
    const w = Number(profile.weight_kg);
    if (!h || !w || h <= 0) return null;
    const m = h / 100;
    return (w / (m * m)).toFixed(1);
  }, [profile.height_cm, profile.weight_kg]);

  const bmiCategory = useMemo(() => {
    if (!bmi) return null;
    const v = Number(bmi);
    if (v < 18.5) return { label: "Underweight", color: "var(--warning)" };
    if (v < 25) return { label: "Normal", color: "var(--success)" };
    if (v < 30) return { label: "Overweight", color: "var(--warning)" };
    return { label: "Obese", color: "var(--danger)" };
  }, [bmi]);

  const tabs = [
    { id: "overview", label: "Overview", icon: "user" },
    { id: "personal", label: "Personal Details", icon: "heart" },
    { id: "health", label: "Health Info", icon: "activity" },
    { id: "goals", label: "Goals", icon: "target" },
    { id: "security", label: "Security", icon: "lock" },
  ];

  const tabIcons = {
    user: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    ),
    heart: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
    ),
    activity: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
    ),
    target: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
    ),
    lock: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    ),
  };

  return (
    <div className="stack-lg page-enter">
      <div className="page-header">
        <h2>My Profile</h2>
        <p>Manage your personal and health information.</p>
      </div>

      <div className="profile-layout">
        {/* Left sidebar */}
        <div className="profile-sidebar">
          <div className="card profile-user-card">
            <div className="profile-avatar">{initials}</div>
            <div className="profile-name">{user?.name || "Patient"}</div>
            <div className="profile-email">{user?.email || "No email"}</div>
            {bmi && (
              <div style={{ marginTop: "0.75rem", padding: "0.5rem 0.75rem", background: "var(--surface-alt)", borderRadius: "var(--radius-md)", fontSize: "0.82rem" }}>
                BMI: <strong style={{ color: bmiCategory?.color }}>{bmi}</strong>{" "}
                <span className="text-muted">({bmiCategory?.label})</span>
              </div>
            )}
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
          {/* ── Overview Tab ── */}
          {activeTab === "overview" && (
            <>
              <div className="card profile-section-card">
                <h3>Account Information</h3>
                <div className="profile-field-grid">
                  <div className="profile-field">
                    <div className="profile-field-label">Full Name</div>
                    <div className="profile-field-value">{user?.name || "-"}</div>
                  </div>
                  <div className="profile-field">
                    <div className="profile-field-label">Email</div>
                    <div className="profile-field-value">{user?.email || "-"}</div>
                  </div>
                </div>
              </div>

              <div className="card profile-section-card">
                <h3>Report Statistics</h3>
                <div className="stats-grid" style={{ marginTop: "0.5rem" }}>
                  <div className="profile-stat-box">
                    <div className="profile-stat-number">{stats.total}</div>
                    <div className="text-muted text-sm">Total Reports</div>
                  </div>
                  <div className="profile-stat-box">
                    <div className="profile-stat-number" style={{ color: "var(--success)" }}>{stats.completed}</div>
                    <div className="text-muted text-sm">Completed</div>
                  </div>
                  <div className="profile-stat-box">
                    <div className="profile-stat-number" style={{ color: "var(--warning)" }}>{stats.pending}</div>
                    <div className="text-muted text-sm">In Progress</div>
                  </div>
                </div>
              </div>

              {/* Quick summary of health data */}
              {profileLoaded && (profile.height_cm || profile.blood_group || profile.gender) && (
                <div className="card profile-section-card">
                  <h3>Health Snapshot</h3>
                  <div className="health-snapshot-grid">
                    {profile.gender && <div className="snapshot-chip"><span className="snapshot-label">Gender</span>{profile.gender}</div>}
                    {profile.age && <div className="snapshot-chip"><span className="snapshot-label">Age</span>{profile.age} yrs</div>}
                    {profile.blood_group && <div className="snapshot-chip"><span className="snapshot-label">Blood</span>{profile.blood_group}</div>}
                    {profile.height_cm && <div className="snapshot-chip"><span className="snapshot-label">Height</span>{profile.height_cm} cm</div>}
                    {profile.weight_kg && <div className="snapshot-chip"><span className="snapshot-label">Weight</span>{profile.weight_kg} kg</div>}
                    {profile.diet_type && <div className="snapshot-chip"><span className="snapshot-label">Diet</span>{profile.diet_type}</div>}
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── Personal Details Tab ── */}
          {activeTab === "personal" && (
            <div className="card profile-section-card">
              <div className="profile-section-header">
                <h3>Personal Details</h3>
                {editing && (
                  <button className="btn btn-primary btn-sm" onClick={handleSaveProfile} disabled={saving}>
                    {saving ? <><span className="spinner spinner-sm" /> Saving...</> : "Save Changes"}
                  </button>
                )}
              </div>
              <div className="profile-form-grid">
                <div className="form-group">
                  <label className="form-label">Height (cm)</label>
                  <input className="form-input" type="number" placeholder="e.g. 170" value={profile.height_cm} onChange={(e) => handleProfileChange("height_cm", e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Weight (kg)</label>
                  <input className="form-input" type="number" placeholder="e.g. 68" value={profile.weight_kg} onChange={(e) => handleProfileChange("weight_kg", e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Age</label>
                  <input className="form-input" type="number" placeholder="e.g. 28" value={profile.age} onChange={(e) => handleProfileChange("age", e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Gender</label>
                  <select className="form-select" value={profile.gender} onChange={(e) => handleProfileChange("gender", e.target.value)}>
                    <option value="">Select gender</option>
                    {GENDER_OPTIONS.map((g) => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>
              </div>
              {bmi && (
                <div className="bmi-display">
                  <span>Your BMI:</span>
                  <strong style={{ color: bmiCategory?.color, fontSize: "1.1rem" }}>{bmi}</strong>
                  <span className="badge" style={{ background: bmiCategory?.color + "22", color: bmiCategory?.color }}>{bmiCategory?.label}</span>
                </div>
              )}
            </div>
          )}

          {/* ── Health Info Tab ── */}
          {activeTab === "health" && (
            <div className="card profile-section-card">
              <div className="profile-section-header">
                <h3>Health Information</h3>
                {editing && (
                  <button className="btn btn-primary btn-sm" onClick={handleSaveProfile} disabled={saving}>
                    {saving ? <><span className="spinner spinner-sm" /> Saving...</> : "Save Changes"}
                  </button>
                )}
              </div>
              <div className="profile-form-grid">
                <div className="form-group">
                  <label className="form-label">Blood Group</label>
                  <select className="form-select" value={profile.blood_group} onChange={(e) => handleProfileChange("blood_group", e.target.value)}>
                    <option value="">Select blood group</option>
                    {BLOOD_GROUPS.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Diet Type</label>
                  <select className="form-select" value={profile.diet_type} onChange={(e) => handleProfileChange("diet_type", e.target.value)}>
                    {DIET_TYPES.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Do you smoke?</label>
                  <select className="form-select" value={profile.smoking} onChange={(e) => handleProfileChange("smoking", e.target.value)}>
                    {SMOKING_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Do you consume alcohol?</label>
                  <select className="form-select" value={profile.alcohol} onChange={(e) => handleProfileChange("alcohol", e.target.value)}>
                    {ALCOHOL_OPTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-group" style={{ marginTop: "var(--space-md)" }}>
                <label className="form-label">Allergies</label>
                <textarea className="form-input" rows={2} placeholder="e.g. Penicillin, Peanuts, Dust..." value={profile.allergies} onChange={(e) => handleProfileChange("allergies", e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Chronic Conditions</label>
                <textarea className="form-input" rows={2} placeholder="e.g. Diabetes, Hypertension, Asthma..." value={profile.chronic_conditions} onChange={(e) => handleProfileChange("chronic_conditions", e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Past Health History</label>
                <textarea className="form-input" rows={2} placeholder="Any significant health events, hereditary conditions..." value={profile.health_history} onChange={(e) => handleProfileChange("health_history", e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Surgeries</label>
                <textarea className="form-input" rows={2} placeholder="List any past surgeries with approximate dates..." value={profile.surgeries} onChange={(e) => handleProfileChange("surgeries", e.target.value)} />
              </div>
            </div>
          )}

          {/* ── Goals Tab ── */}
          {activeTab === "goals" && (
            <div className="card profile-section-card">
              <div className="profile-section-header">
                <h3>Health Goals</h3>
                {editing && (
                  <button className="btn btn-primary btn-sm" onClick={handleSaveProfile} disabled={saving}>
                    {saving ? <><span className="spinner spinner-sm" /> Saving...</> : "Save Changes"}
                  </button>
                )}
              </div>
              <p className="text-muted text-sm" style={{ marginBottom: "var(--space-md)" }}>
                Set a personal health goal to stay motivated. This helps us personalize your insights.
              </p>
              <div className="form-group">
                <label className="form-label">Your Health Goal</label>
                <textarea
                  className="form-input"
                  rows={4}
                  placeholder="e.g. Lose 5 kg in 3 months, Improve cholesterol levels, Build a consistent exercise routine, Manage blood sugar..."
                  value={profile.health_goal}
                  onChange={(e) => handleProfileChange("health_goal", e.target.value)}
                />
              </div>

              {/* Suggested goals */}
              <div style={{ marginTop: "var(--space-lg)" }}>
                <div className="form-label" style={{ marginBottom: "var(--space-sm)" }}>Quick Goal Suggestions</div>
                <div className="goal-chips">
                  {[
                    "Lose weight",
                    "Build muscle",
                    "Improve heart health",
                    "Lower cholesterol",
                    "Manage diabetes",
                    "Better sleep",
                    "Reduce stress",
                    "Quit smoking",
                    "Eat healthier",
                    "Regular checkups",
                  ].map((g) => (
                    <button
                      key={g}
                      className={`goal-chip ${profile.health_goal?.includes(g) ? "active" : ""}`}
                      onClick={() => {
                        const current = profile.health_goal || "";
                        const next = current ? `${current}, ${g}` : g;
                        handleProfileChange("health_goal", next);
                      }}
                      type="button"
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Security Tab ── */}
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
        </div>
      </div>
    </div>
  );
}
