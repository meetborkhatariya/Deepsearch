import { useState, useRef, useEffect } from "react";
import { toast } from "react-toastify";
import { generateVoice } from "../../services/reportService";
import { useAuth } from "../../hooks/useAuth";

export default function VoiceSummaryButton({ analysis, onVoiceGenerated, compact = false }) {
  const { user } = useAuth();
  const [generating, setGenerating] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef(null);

  const voiceExplanation = analysis?.voice_explanation;
  const hasVoice = !!voiceExplanation?.audio_base64;
  const audioBase64 = voiceExplanation?.audio_base64;

  useEffect(() => {
    if (!audioBase64) return;

    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    const audioSrc = `data:audio/wav;base64,${audioBase64}`;
    const nextAudio = new Audio(audioSrc);
    nextAudio.onended = () => setIsPlaying(false);
    audioRef.current = nextAudio;

    return () => {
      nextAudio.pause();
      nextAudio.onended = null;
    };
  }, [audioBase64]);

  const handleGenerate = async () => {
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
      await generateVoice({ reportId, userId, txnId });
      toast.success("Voice summary generated successfully!");
      if (onVoiceGenerated) onVoiceGenerated();
    } catch (error) {
      const message = error?.response?.data?.detail || "Failed to generate voice summary.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  };

  const handlePlayToggle = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const normalizedStatus = (analysis.status || "").toUpperCase();
  if (!["SUCCESS", "COMPLETED"].includes(normalizedStatus)) return null;

  return (
    <div className={`voice-summary ${compact ? "voice-summary-compact" : ""}`}>
      {hasVoice ? (
        <button 
          className="primary-btn" 
          onClick={handlePlayToggle}
        >
          {isPlaying ? "Pause Voice Summary" : "Listen Voice Summary"}
        </button>
      ) : (
        <button 
          className="secondary-btn" 
          onClick={handleGenerate} 
          disabled={generating}
        >
          {generating ? "Generating Voice..." : "Generate Voice Summary"}
        </button>
      )}
    </div>
  );
}
