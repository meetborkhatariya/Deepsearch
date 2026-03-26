import { useState } from "react";
import { toast } from "react-toastify";
import { generateVoice } from "../../services/reportService";
import { useAuth } from "../../hooks/useAuth";
import AudioPlayer from "../common/AudioPlayer";

const LANGUAGES = [
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "gujarati", label: "Gujarati" },
  { value: "marathi", label: "Marathi" },
  { value: "tamil", label: "Tamil" },
  { value: "kannada", label: "Kannada" },
  { value: "malayalam", label: "Malayalam" },
  { value: "bangla", label: "Bengali" },
];

export default function VoiceSummaryButton({ analysis, onVoiceGenerated, compact = false }) {
  const { user } = useAuth();
  const [generating, setGenerating] = useState(false);
  const [language, setLanguage] = useState("english");
  // Local audio state so we show the player immediately after generation
  const [localAudio, setLocalAudio] = useState(null);
  const [localLang, setLocalLang] = useState(null);

  const voiceExplanation = analysis?.voice_explanation;
  const propsAudio = voiceExplanation?.audio_base64;
  // Prefer local audio (freshly generated) over props (stale until parent re-fetches)
  const audioBase64 = localAudio || propsAudio;
  const hasVoice = !!audioBase64;

  const handleGenerate = async (isRegenerate = false) => {
    const reportId = analysis.reportId || analysis.report_id;
    const txnId = analysis.txn_id;
    const userId = analysis.user_id || user?.id;
    if (!reportId && !txnId) {
      toast.error("Missing report identity for voice generation.");
      return;
    }
    if (!userId) {
      toast.error("Missing user identity for voice generation.");
      return;
    }
    setGenerating(true);
    try {
      const result = await generateVoice({ reportId, userId, txnId, language });
      // Capture the returned audio immediately
      const newAudio = result?.voice_explanation?.audio_base64;
      if (newAudio) {
        setLocalAudio(newAudio);
        setLocalLang(language);
      }
      const langLabel = LANGUAGES.find((l) => l.value === language)?.label || language;
      toast.success(`Voice summary ${isRegenerate ? "regenerated" : "generated"} in ${langLabel}!`);
      if (onVoiceGenerated) onVoiceGenerated();
    } catch (error) {
      const message = error?.response?.data?.detail || "Failed to generate voice summary.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const normalizedStatus = (analysis.status || "").toUpperCase();
  if (!["SUCCESS", "COMPLETED"].includes(normalizedStatus)) return null;

  return (
    <div className="voice-section">
      {hasVoice && (
        <div>
          <AudioPlayer base64={audioBase64} key={audioBase64?.slice(-20)} />
          {localLang && (
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>
              Language: {LANGUAGES.find((l) => l.value === localLang)?.label || localLang}
            </p>
          )}
        </div>
      )}

      <div className="voice-controls">
        <div className="language-select-wrap">
          <label htmlFor={`voice-lang-${analysis.txn_id || "x"}`}>Language:</label>
          <select
            id={`voice-lang-${analysis.txn_id || "x"}`}
            className="form-select"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            style={{ minWidth: 130, padding: "0.4rem 2rem 0.4rem 0.6rem", fontSize: "0.82rem" }}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>

        {hasVoice ? (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => handleGenerate(true)}
            disabled={generating}
          >
            {generating ? (
              <>
                <span className="spinner spinner-sm" style={{ display: "inline-block" }} />
                Regenerating...
              </>
            ) : (
              "Regenerate Voice"
            )}
          </button>
        ) : (
          <button
            className="btn btn-primary btn-sm"
            onClick={() => handleGenerate(false)}
            disabled={generating}
          >
            {generating ? (
              <>
                <span className="spinner spinner-sm" style={{ display: "inline-block" }} />
                Generating...
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 15, height: 15 }}><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                Generate Voice Summary
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
