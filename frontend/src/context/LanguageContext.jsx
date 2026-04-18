/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState } from "react";

const LANGUAGES = [
  { value: "english", label: "English", flag: "🇬🇧" },
  { value: "hindi", label: "हिन्दी", flag: "🇮🇳" },
  { value: "gujarati", label: "ગુજરાતી", flag: "🇮🇳" },
];

const TRANSLATIONS = {
  english: {
    welcome_back: "Welcome back",
    sign_in_subtitle: "Sign in to securely manage your report analyses and health records.",
    create_account: "Create your account",
    sign_up_subtitle: "Set up secure access to upload reports and review your health trends.",
    email: "Email",
    password: "Password",
    confirm_password: "Confirm Password",
    full_name: "Full Name",
    sign_in: "Sign in",
    signing_in: "Signing in...",
    create_account_btn: "Create account",
    creating_account: "Creating account...",
    new_patient: "New patient?",
    already_have_account: "Already have an account?",
    sign_up_link: "Create an account",
    sign_in_link: "Sign in",
    language: "Language",
    dashboard: "Dashboard",
    deep_research: "Deep Research",
    store_report: "Store Report",
    health_records: "Health Records",
    profile: "Profile",
    upload_analyze: "Upload & Analyze",
    overview: "Overview",
    reports: "Reports",
    data: "Data",
    account: "Account",
    logout: "Logout",
    show_password: "Show password",
    hide_password: "Hide password",
  },
  hindi: {
    welcome_back: "वापसी पर स्वागत है",
    sign_in_subtitle: "अपनी रिपोर्ट विश्लेषण और स्वास्थ्य रिकॉर्ड को सुरक्षित रूप से प्रबंधित करने के लिए साइन इन करें।",
    create_account: "अपना खाता बनाएं",
    sign_up_subtitle: "रिपोर्ट अपलोड करने और अपने स्वास्थ्य रुझान की समीक्षा करने के लिए सुरक्षित पहुंच सेट करें।",
    email: "ईमेल",
    password: "पासवर्ड",
    confirm_password: "पासवर्ड की पुष्टि करें",
    full_name: "पूरा नाम",
    sign_in: "साइन इन",
    signing_in: "साइन इन हो रहा है...",
    create_account_btn: "खाता बनाएं",
    creating_account: "खाता बनाया जा रहा है...",
    new_patient: "नए मरीज?",
    already_have_account: "पहले से खाता है?",
    sign_up_link: "खाता बनाएं",
    sign_in_link: "साइन इन करें",
    language: "भाषा",
    dashboard: "डैशबोर्ड",
    deep_research: "गहन अनुसंधान",
    store_report: "रिपोर्ट स्टोर करें",
    health_records: "स्वास्थ्य रिकॉर्ड",
    profile: "प्रोफ़ाइल",
    upload_analyze: "अपलोड और विश्लेषण",
    overview: "अवलोकन",
    reports: "रिपोर्ट",
    data: "डेटा",
    account: "खाता",
    logout: "लॉग आउट",
    show_password: "पासवर्ड दिखाएं",
    hide_password: "पासवर्ड छुपाएं",
  },
  gujarati: {
    welcome_back: "પાછા આવવા બદલ આવકાર",
    sign_in_subtitle: "તમારા રિપોર્ટ વિશ્લેષણ અને આરોગ્ય રેકોર્ડને સુરક્ષિત રીતે સંચાલિત કરવા સાઇન ઇન કરો.",
    create_account: "તમારું ખાતું બનાવો",
    sign_up_subtitle: "રિપોર્ટ અપલોડ કરવા અને તમારા આરોગ્ય વલણોની સમીક્ષા કરવા માટે સુરક્ષિત ઍક્સેસ સેટ કરો.",
    email: "ઇમેઇલ",
    password: "પાસવર્ડ",
    confirm_password: "પાસવર્ડની પુષ્ટિ કરો",
    full_name: "પૂરું નામ",
    sign_in: "સાઇન ઇન",
    signing_in: "સાઇન ઇન થઈ રહ્યું છે...",
    create_account_btn: "ખાતું બનાવો",
    creating_account: "ખાતું બનાવવામાં આવી રહ્યું છે...",
    new_patient: "નવા દર્દી?",
    already_have_account: "પહેલાથી ખાતું છે?",
    sign_up_link: "ખાતું બનાવો",
    sign_in_link: "સાઇન ઇન કરો",
    language: "ભાષા",
    dashboard: "ડેશબોર્ડ",
    deep_research: "ઊંડું સંશોધન",
    store_report: "રિપોર્ટ સ્ટોર કરો",
    health_records: "આરોગ્ય રેકોર્ડ",
    profile: "પ્રોફાઇલ",
    upload_analyze: "અપલોડ અને વિશ્લેષણ",
    overview: "ઝાંખી",
    reports: "રિપોર્ટ",
    data: "ડેટા",
    account: "ખાતું",
    logout: "લૉગ આઉટ",
    show_password: "પાસવર્ડ બતાવો",
    hide_password: "પાસવર્ડ છુપાવો",
  },
};

const LanguageContext = createContext(null);

export const LANGUAGE_OPTIONS = LANGUAGES;

export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState(() => {
    try {
      return localStorage.getItem("app_language") || "english";
    } catch {
      return "english";
    }
  });

  const setLanguage = useCallback((lang) => {
    setLanguageState(lang);
    try {
      localStorage.setItem("app_language", lang);
    } catch {
      // ignore
    }
  }, []);

  const t = useCallback(
    (key) => TRANSLATIONS[language]?.[key] || TRANSLATIONS.english[key] || key,
    [language]
  );

  const value = useMemo(
    () => ({ language, setLanguage, t, languages: LANGUAGES }),
    [language, setLanguage, t]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useLanguage must be used within LanguageProvider");
  return ctx;
}
