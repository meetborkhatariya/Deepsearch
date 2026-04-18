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

export default function VoiceSummaryButton({ analysis, onVoiceGenerated }) {
  const { user } = useAuth();
  const [generating, setGenerating] = useState(false);
  const [language, setLanguage] = useState("english");
  // Local state so we show results immediately after generation
  const [localAudio, setLocalAudio] = useState(null);
  const [localScript, setLocalScript] = useState(null);
  const [localLang, setLocalLang] = useState(null);
  // Key to force AudioPlayer remount on new audio
  const [audioKey, setAudioKey] = useState(0);

  const voiceExplanation = analysis?.voice_explanation;
  const propsAudio = voiceExplanation?.audio_base64;
  const propsScript = voiceExplanation?.voice_agent_script;
  // Prefer local (freshly generated) over props (stale until parent re-fetches)
  const audioBase64 = localAudio || propsAudio;
  const voiceScript = localScript || propsScript;
  const hasVoice = !!audioBase64;
  const hasVoiceData = hasVoice || !!voiceScript;

  // Displayed language: local overrides props
  const displayedLang = localLang || voiceExplanation?.language || null;

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
      const ve = result?.voice_explanation || {};
      const newAudio = ve.audio_base64 || result?.audio_base64;
      const newScript = ve.voice_agent_script || result?.voice_agent_script;

      // Always update language and bump key so UI reflects the generation
      setLocalLang(language);
      setAudioKey((k) => k + 1);
      if (newAudio) setLocalAudio(newAudio);
      if (newScript) setLocalScript(newScript);

      const langLabel = LANGUAGES.find((l) => l.value === language)?.label || language;
      if (newAudio) {
        toast.success(`Voice summary ${isRegenerate ? "regenerated" : "generated"} in ${langLabel}!`);
      } else if (newScript) {
        toast.success(`Voice script generated in ${langLabel} (audio unavailable).`);
      } else {
        toast.warning("Voice generation completed but no audio was returned.");
      }
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
          <AudioPlayer base64={audioBase64} key={`audio-${audioKey}-${(audioBase64 || "").slice(-20)}`} />
          {displayedLang && (
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>
              Language: {LANGUAGES.find((l) => l.value === displayedLang)?.label || displayedLang}
            </p>
          )}
        </div>
      )}

      {/* Show script text when audio is not available but script exists */}
      {!hasVoice && voiceScript && (
        <div style={{ padding: "0.65rem 0.85rem", background: "var(--warning-light)", borderRadius: "var(--radius-md)", fontSize: "0.82rem", color: "#92400e", display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 15, height: 15, flexShrink: 0 }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Audio generation failed — try regenerating with the same language.
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

        {hasVoiceData ? (
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
              <>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 15, height: 15 }}><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
                Regenerate Voice
              </>
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
