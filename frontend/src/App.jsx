import { Navigate, Route, Routes } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import ProtectedRoute from "./components/common/ProtectedRoute";
import MainLayout from "./components/layout/MainLayout";
import { useAuth } from "./hooks/useAuth";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import ProfilePage from "./pages/ProfilePage";
import ReportDetailPage from "./pages/ReportDetailPage";
import RecordsPage from "./pages/RecordsPage";
import SignupPage from "./pages/SignupPage";
import StorePage from "./pages/StorePage";
import TrendsPage from "./pages/TrendsPage";
import UploadPage from "./pages/UploadPage";

function HomeRedirect() {
  const { isAuthenticated } = useAuth();
  return <Navigate to={isAuthenticated ? "/dashboard" : "/login"} replace />;
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<MainLayout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/records" element={<RecordsPage />} />
            <Route path="/records/:txnId" element={<ReportDetailPage />} />
            <Route path="/trends" element={<TrendsPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/store" element={<StorePage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <ToastContainer
        position="top-right"
        autoClose={3500}
        hideProgressBar
        newestOnTop
        closeOnClick
        pauseOnHover
      />
    </>
  );
}
