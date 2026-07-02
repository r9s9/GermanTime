import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { GermanText } from "../components/GermanText";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";
import { startMicCapture } from "../lib/micCapture";
import { ChunkedPlayer } from "../lib/voicePlayer";
import { VoiceEvent, VoiceSocket } from "../lib/voiceWs";

type Scenario = { id: string; title_de: string; title_en: string; min_level: string };
type Turn = { id: string; role: "user" | "assistant"; text: string; interrupted?: boolean };
type PipelineState = "connecting" | "listening" | "thinking" | "speaking";

export default function Sprechen() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const blockId = searchParams.get("block_id") ?? undefined;
  const scenarioIdParam = searchParams.get("scenario_id") ?? undefined;

  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [phase, setPhase] = useState<"pick" | "active" | "ended">("pick");
  const [pipelineState, setPipelineState] = useState<PipelineState>("connecting");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [liveAssistant, setLiveAssistant] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<{ minutes: number } | null>(null);
  const [lastLatency, setLastLatency] = useState<Record<string, number> | null>(null);

  const convIdRef = useRef<string | null>(null);
  const wsRef = useRef<VoiceSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playerRef = useRef<ChunkedPlayer | null>(null);
  const micStopRef = useRef<(() => void) | null>(null);
  const startedAtRef = useRef(0);
  const currentAssistantId = useRef<string | null>(null);

  useEffect(() => {
    api<Scenario[]>("/api/conversations/scenarios").then(setScenarios).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (scenarioIdParam && scenarios.length) {
      begin(scenarioIdParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarios, scenarioIdParam]);

  useEffect(() => () => cleanup(), []);

  function cleanup() {
    micStopRef.current?.();
    micStopRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }

  async function begin(scenarioId: string) {
    setError(null);
    setPhase("active");
    setPipelineState("connecting");
    setTurns([]);
    setLiveAssistant("");
    startedAtRef.current = Date.now();

    try {
      const res = await api<{ conv_id: string }>("/api/conversations", { json: { scenario_id: scenarioId } });
      convIdRef.current = res.conv_id;

      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const player = new ChunkedPlayer(ctx);
      player.onPlaybackChange = (playing) => setPipelineState((s) => (playing ? "speaking" : s === "speaking" ? "listening" : s));
      playerRef.current = player;

      const ws = new VoiceSocket(res.conv_id, handleEvent, (data) => {
        // tts_begin (carrying sample rate) always arrives immediately before its audio frame
        const sr = lastSrRef.current ?? 22050;
        player.enqueuePcm16(data, sr);
      });
      wsRef.current = ws;

      const mic = await startMicCapture(ctx, (frame) => ws.sendPcm(frame));
      micStopRef.current = mic.stop;
      setPipelineState("listening");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("pick");
      cleanup();
    }
  }

  const lastSrRef = useRef<number | null>(null);

  function handleEvent(e: VoiceEvent) {
    switch (e.t) {
      case "vad":
        setPipelineState(e.state === "speech_start" ? "listening" : "thinking");
        break;
      case "stt_final":
        setTurns((t) => [...t, { id: e.turn_id, role: "user", text: e.text }]);
        setPipelineState("thinking");
        break;
      case "llm_delta":
        setLiveAssistant((prev) => prev + e.text);
        break;
      case "tts_begin":
        lastSrRef.current = e.sr;
        currentAssistantId.current = e.turn_id;
        setPipelineState("speaking");
        break;
      case "tts_end":
        setTurns((t) => [...t, { id: e.turn_id, role: "assistant", text: liveAssistantRef.current }]);
        setLiveAssistant("");
        break;
      case "barge_in":
        playerRef.current?.flush();
        if (currentAssistantId.current) {
          setTurns((t) => [...t, { id: currentAssistantId.current!, role: "assistant", text: liveAssistantRef.current, interrupted: true }]);
        }
        setLiveAssistant("");
        setPipelineState("listening");
        break;
      case "turn_stats":
        setLastLatency(e.latency);
        break;
      case "error":
        setError(e.message);
        break;
    }
  }

  // keep a ref mirror of liveAssistant so the tts_end/barge_in handlers (called
  // from WS callbacks, closing over stale state) can read the latest value
  const liveAssistantRef = useRef("");
  useEffect(() => {
    liveAssistantRef.current = liveAssistant;
  }, [liveAssistant]);

  async function end() {
    const convId = convIdRef.current;
    cleanup();
    if (convId) {
      try {
        const res = await api<{ minutes: number }>(`/api/conversations/${convId}/end`, { json: { block_id: blockId ?? null } });
        setSummary(res);
      } catch {
        setSummary({ minutes: Math.round(((Date.now() - startedAtRef.current) / 60000) * 10) / 10 });
      }
    }
    setPhase("ended");
  }

  if (phase === "ended" && summary) {
    return (
      <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="card mx-auto mt-10 flex max-w-md flex-col items-center gap-3 px-8 py-14 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-mint/10 text-mint">
          <Icon name="check" size={26} />
        </div>
        <h2 className="text-xl font-semibold">Gespräch beendet</h2>
        <p className="text-mute">{summary.minutes} Minuten gesprochen</p>
        <button className="btn-gold mt-2" onClick={() => navigate("/")}>Zurück zu Heute</button>
      </motion.div>
    );
  }

  if (phase === "pick") {
    return (
      <div>
        <h1 className="text-2xl font-semibold">Sprechen</h1>
        <p className="mt-1 text-sm text-mute">Wähle eine Situation zum Üben.</p>
        {error && <p className="mt-4 text-sm text-ember">{error}</p>}
        <div className="mt-6 grid grid-cols-2 gap-2 md:grid-cols-3">
          {scenarios.map((s) => (
            <button key={s.id} onClick={() => begin(s.id)} className="card flex flex-col items-start gap-1 px-4 py-3 text-left transition-colors hover:bg-white/5">
              <span className="text-xs text-mute">{s.min_level}+</span>
              <span className="text-sm font-medium">{s.title_de}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  const stateLabel: Record<PipelineState, string> = {
    connecting: "Verbinde …", listening: "Ich höre zu …", thinking: "Einen Moment …", speaking: "…",
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-mute">
          <StateOrb state={pipelineState} />
          {stateLabel[pipelineState]}
        </div>
        <button className="btn-ghost" onClick={end}><Icon name="x" size={16} /> Beenden</button>
      </div>

      {error && <p className="mb-3 text-sm text-ember">{error}</p>}

      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        <AnimatePresence initial={false}>
          {turns.map((t) => (
            <motion.div
              key={t.id + t.role} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${t.role === "user" ? "bg-gold/10 text-ink" : "bg-white/5"} ${t.interrupted ? "opacity-60" : ""}`}>
                <GermanText text={t.text} />
                {t.interrupted && <span className="ml-1 text-[10px] text-mute">(unterbrochen)</span>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {liveAssistant && (
          <div className="flex justify-start">
            <div className="max-w-[75%] rounded-2xl bg-white/5 px-4 py-2 text-sm">
              <GermanText text={liveAssistant} />
            </div>
          </div>
        )}
      </div>

      {lastLatency?.total_ms !== undefined && (
        <div className="mt-2 text-right text-[10px] text-mute">{Math.round(lastLatency.total_ms)} ms</div>
      )}
    </div>
  );
}

function StateOrb({ state }: { state: PipelineState }) {
  const color = state === "listening" ? "bg-mint" : state === "speaking" ? "bg-gold" : "bg-sky";
  return (
    <motion.span
      className={`inline-block h-2.5 w-2.5 rounded-full ${color}`}
      animate={state === "connecting" || state === "thinking" ? { opacity: [1, 0.3, 1] } : { scale: [1, 1.3, 1] }}
      transition={{ repeat: Infinity, duration: state === "listening" ? 1.2 : 0.8 }}
    />
  );
}
