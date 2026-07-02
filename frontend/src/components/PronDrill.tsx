import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";
import { PronCaption } from "./PronCaption";
import { api } from "../lib/api";
import { startMicCapture } from "../lib/micCapture";
import { WordScore } from "../lib/voiceWs";
import { encodeWav } from "../lib/wavEncode";

const SAMPLE_RATE = 16000;

type Drill = {
  phoneme: string; label_de: string; tip_de: string | null; tip_en: string | null;
  text_de: string; translation_en: string; occurrences: number; audio_url: string;
};
type AttemptResult = { overall: number; words: WordScore[] };

export function PronDrill({ phoneme, onClose }: { phoneme: string; onClose: () => void }) {
  const [drill, setDrill] = useState<Drill | null>(null);
  const [loading, setLoading] = useState(true);
  const [recording, setRecording] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const micStopRef = useRef<(() => void) | null>(null);
  const framesRef = useRef<Int16Array[]>([]);

  useEffect(() => {
    loadDrill();
    return () => {
      micStopRef.current?.();
      ctxRef.current?.close().catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phoneme]);

  async function loadDrill() {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const d = await api<Drill>("/api/pron/drill", { json: { phoneme } });
      setDrill(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function playReference() {
    if (drill) new Audio(drill.audio_url).play().catch(() => {});
  }

  async function startRecording() {
    setError(null);
    setResult(null);
    framesRef.current = [];
    try {
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const mic = await startMicCapture(ctx, (frame) => {
        framesRef.current.push(new Int16Array(frame));
      });
      micStopRef.current = mic.stop;
      setRecording(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function stopRecording() {
    micStopRef.current?.();
    micStopRef.current = null;
    await ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
    setRecording(false);

    const totalLen = framesRef.current.reduce((n, f) => n + f.length, 0);
    if (totalLen === 0 || !drill) return;
    const merged = new Int16Array(totalLen);
    let off = 0;
    for (const f of framesRef.current) {
      merged.set(f, off);
      off += f.length;
    }
    framesRef.current = [];

    setScoring(true);
    try {
      const wav = encodeWav(merged, SAMPLE_RATE);
      const form = new FormData();
      form.append("file", wav, "attempt.wav");
      const res = await api<AttemptResult>(
        `/api/pron/attempt?ref_text=${encodeURIComponent(drill.text_de)}`,
        { method: "POST", body: form },
      );
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScoring(false);
    }
  }

  return (
    <div className="card flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-mute">Ausspracheübung</div>
          <h3 className="text-lg font-semibold">{drill?.label_de ?? phoneme}</h3>
        </div>
        <button className="btn-ghost !p-2" onClick={onClose} aria-label="Schließen">
          <Icon name="x" size={16} />
        </button>
      </div>

      {drill?.tip_de && <p className="text-sm text-mute">{drill.tip_de}</p>}

      {loading && <p className="text-sm text-mute">Lädt …</p>}
      {error && <p className="text-sm text-ember">{error}</p>}

      {drill && !loading && (
        <>
          <div className="rounded-xl bg-white/5 px-4 py-3">
            <p className="text-base">
              {result ? <PronCaption text={drill.text_de} words={result.words} /> : drill.text_de}
            </p>
            <p className="mt-1 text-xs text-mute">{drill.translation_en}</p>
          </div>

          <div className="flex items-center gap-3">
            <button className="btn-ghost" onClick={playReference}>
              <Icon name="play" size={16} /> Anhören
            </button>
            {!recording ? (
              <button className="btn-gold" onClick={startRecording} disabled={scoring}>
                <Icon name="mic" size={16} /> Aufnehmen
              </button>
            ) : (
              <button className="btn-gold !bg-ember" onClick={stopRecording}>
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-black" /> Stopp
              </button>
            )}
            {scoring && <span className="text-sm text-mute">Wird bewertet …</span>}
          </div>

          {result && (
            <div className="flex items-center justify-between border-t border-line pt-3">
              <div className="text-sm">
                Bewertung: <span className={result.overall >= 80 ? "text-mint" : result.overall >= 60 ? "text-gold" : "text-ember"}>
                  {Math.round(result.overall)}/100
                </span>
              </div>
              <div className="flex gap-2">
                <button className="btn-ghost !text-xs" onClick={() => { setResult(null); }}>Nochmal</button>
                <button className="btn-ghost !text-xs" onClick={loadDrill}>Neuer Satz</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
