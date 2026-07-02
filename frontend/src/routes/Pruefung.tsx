import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { GermanText } from "../components/GermanText";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";
import { startMicCapture } from "../lib/micCapture";
import { ChunkedPlayer } from "../lib/voicePlayer";
import { VoiceEvent, VoiceSocket } from "../lib/voiceWs";

type ModuleStatus = "locked" | "not_started" | "active" | "done";
type Section = {
  id: string; teil: number; kind: string;
  shape: "comprehension" | "matching" | "writing" | "speaking";
  payload: Record<string, any>;
  status: "active" | "done";
};
type ModuleState = {
  status: ModuleStatus; score: number | null; max_score: number | null;
  sections?: Section[]; conv_id?: string;
};
type ExamState = {
  id: string; level: string; status: "active" | "done"; module_order: string[];
  modules: Record<string, ModuleState>;
  per_module?: Record<string, { score: number; max_score: number; pct: number }>;
  total_pct?: number; passed?: boolean;
};

const MODULE_LABEL: Record<string, string> = {
  hoeren: "Hören", lesen: "Lesen", schreiben: "Schreiben", sprechen: "Sprechen",
};
const MODULE_ICON: Record<string, string> = {
  hoeren: "ear", lesen: "book", schreiben: "pen", sprechen: "mic",
};

export default function Pruefung() {
  const [exam, setExam] = useState<ExamState | null>(null);
  const [activeModule, setActiveModule] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function startExam(level: string) {
    setStarting(true);
    setError(null);
    try {
      const state = await api<ExamState>("/api/exams/start", { json: { level } });
      setExam(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  async function openModule(name: string) {
    if (!exam) return;
    const mod = exam.modules[name];
    if (mod.status === "not_started") {
      setError(null);
      try {
        const state = await api<ExamState>(`/api/exams/${exam.id}/modules/${name}/start`, { method: "POST" });
        setExam(state);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
    }
    setActiveModule(name);
  }

  if (!exam) {
    return <LevelPicker onPick={startExam} starting={starting} error={error} />;
  }

  if (exam.status === "done") {
    return <ExamReport exam={exam} onRestart={() => setExam(null)} />;
  }

  if (activeModule) {
    return (
      <ModuleView
        exam={exam}
        moduleName={activeModule}
        onBack={() => setActiveModule(null)}
        onExamUpdate={setExam}
      />
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Prüfung: {exam.level}</h1>
          <p className="mt-1 text-sm text-mute">Absolviere alle vier Module der Reihe nach.</p>
        </div>
      </div>
      {error && <p className="mb-4 text-sm text-ember">{error}</p>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {exam.module_order.map((name) => (
          <ModuleCard key={name} name={name} state={exam.modules[name]} onOpen={() => openModule(name)} />
        ))}
      </div>
    </div>
  );
}

function LevelPicker({
  onPick, starting, error,
}: { onPick: (level: string) => void; starting: boolean; error: string | null }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Prüfung</h1>
      <p className="mt-1 text-sm text-mute">Goethe-Probeprüfung mit echtem Zeitlimit und Bewertung.</p>
      {error && <p className="mt-4 text-sm text-ember">{error}</p>}
      <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        {["A1", "A2", "B1"].map((level) => (
          <button
            key={level} disabled={starting} onClick={() => onPick(level)}
            className="card flex flex-col items-start gap-1 px-5 py-4 text-left transition-colors hover:bg-white/5 disabled:opacity-60"
          >
            <span className="text-lg font-semibold">{level}</span>
            <span className="text-xs text-mute">
              {level === "A1" ? "Start Deutsch 1" : level === "A2" ? "Goethe-Zertifikat A2" : "Goethe-Zertifikat B1"}
            </span>
          </button>
        ))}
      </div>
      {starting && <p className="mt-4 text-sm text-mute">Prüfung wird vorbereitet …</p>}
    </div>
  );
}

function ModuleCard({ name, state, onOpen }: { name: string; state: ModuleState; onOpen: () => void }) {
  const locked = state.status === "locked";
  const done = state.status === "done";
  return (
    <button
      onClick={onOpen} disabled={locked}
      className={`card flex items-center gap-4 px-5 py-4 text-left transition-colors ${locked ? "opacity-50" : "hover:bg-white/5"}`}
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${done ? "bg-mint/15 text-mint" : "bg-white/5 text-mute"}`}>
        <Icon name={done ? "check" : MODULE_ICON[name] ?? "book"} size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{MODULE_LABEL[name] ?? name}</div>
        <div className="text-xs text-mute">
          {locked ? "Gesperrt" : done ? `${state.score}/${state.max_score} Punkte` : state.status === "active" ? "In Bearbeitung" : "Bereit"}
        </div>
      </div>
      {!locked && !done && <Icon name="play" size={16} className="shrink-0 text-mute" />}
    </button>
  );
}

function ExamReport({ exam, onRestart }: { exam: ExamState; onRestart: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mx-auto max-w-lg">
      <div className="card flex flex-col items-center gap-3 px-8 py-10 text-center">
        <div className={`flex h-16 w-16 items-center justify-center rounded-2xl ${exam.passed ? "bg-mint/10 text-mint" : "bg-ember/10 text-ember"}`}>
          <Icon name={exam.passed ? "check" : "x"} size={30} />
        </div>
        <h2 className="text-xl font-semibold">{exam.passed ? "Bestanden!" : "Noch nicht bestanden"}</h2>
        <p className="text-mute">Gesamt: {exam.total_pct}%</p>

        <div className="mt-4 flex w-full flex-col gap-2">
          {exam.module_order.map((name) => {
            const m = exam.per_module?.[name];
            if (!m) return null;
            return (
              <div key={name} className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-2 text-sm">
                <span>{MODULE_LABEL[name] ?? name}</span>
                <span className={m.pct >= 60 ? "text-mint" : "text-ember"}>{m.score}/{m.max_score} ({m.pct}%)</span>
              </div>
            );
          })}
        </div>

        <button className="btn-gold mt-4" onClick={onRestart}>Neue Prüfung</button>
      </div>
    </motion.div>
  );
}

function ModuleView({
  exam, moduleName, onBack, onExamUpdate,
}: { exam: ExamState; moduleName: string; onBack: () => void; onExamUpdate: (e: ExamState) => void }) {
  const mod = exam.modules[moduleName];

  if (moduleName === "sprechen" && mod.conv_id) {
    return (
      <ExamSpeaking
        examId={exam.id} convId={mod.conv_id} label={MODULE_LABEL[moduleName]}
        onBack={onBack}
        onFinished={onExamUpdate}
      />
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <button className="btn-ghost !p-2" onClick={onBack} aria-label="Zurück"><Icon name="arrowRight" size={16} className="rotate-180" /></button>
        <h1 className="text-2xl font-semibold">{MODULE_LABEL[moduleName] ?? moduleName}</h1>
      </div>
      <div className="flex flex-col gap-4">
        {(mod.sections ?? []).map((sec) => (
          <SectionCard
            key={sec.id} examId={exam.id} moduleName={moduleName} section={sec}
            onSubmitted={onExamUpdate}
          />
        ))}
      </div>
    </div>
  );
}

function SectionCard({
  examId, moduleName, section, onSubmitted,
}: { examId: string; moduleName: string; section: Section; onSubmitted: (e: ExamState) => void }) {
  const done = section.status === "done";
  const [submitting, setSubmitting] = useState(false);

  async function submit(response: unknown) {
    if (done || submitting) return;
    setSubmitting(true);
    try {
      const state = await api<ExamState>(`/api/exams/${examId}/sections/${section.id}/answer`, { json: { response } });
      onSubmitted(state);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={`card p-5 ${done ? "opacity-70" : ""}`}>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-mute">Teil {section.teil}</span>
        {done && <span className="chip !border-mint/40 !text-mint">Abgeschickt</span>}
      </div>
      {section.shape === "comprehension" && <ComprehensionBody payload={section.payload} disabled={done || submitting} submit={submit} />}
      {section.shape === "matching" && <MatchingSectionBody payload={section.payload} disabled={done || submitting} submit={submit} />}
      {section.shape === "writing" && <WritingBody payload={section.payload} disabled={done || submitting} submit={submit} />}
    </div>
  );
}

function ComprehensionBody({
  payload, disabled, submit,
}: { payload: any; disabled: boolean; submit: (r: unknown) => void }) {
  const questions: { prompt_de: string; options: string[] }[] = payload.questions;
  const [answers, setAnswers] = useState<(number | null)[]>(questions.map(() => null));
  const allAnswered = answers.every((a) => a !== null);

  return (
    <div>
      <p className="mb-4 whitespace-pre-line text-sm text-ink/90"><GermanText text={payload.passage_de} /></p>
      <div className="flex flex-col gap-4">
        {questions.map((q, qi) => (
          <div key={qi}>
            <p className="mb-2 text-sm font-medium"><GermanText text={q.prompt_de} /></p>
            <div className="flex flex-col gap-1.5">
              {q.options.map((opt, oi) => (
                <button
                  key={oi} disabled={disabled}
                  onClick={() => setAnswers((a) => a.map((v, i) => (i === qi ? oi : v)))}
                  className={`rounded-lg border px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-default ${
                    answers[qi] === oi ? "border-gold/50 bg-gold/10" : "border-line bg-white/5 hover:bg-white/10"
                  }`}
                >
                  <GermanText text={opt} />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {!disabled && (
        <button className="btn-ghost mt-4 w-full" disabled={!allAnswered}
          onClick={() => submit({ indices: answers })}>
          Teil abschicken
        </button>
      )}
    </div>
  );
}

function MatchingSectionBody({
  payload, disabled, submit,
}: { payload: any; disabled: boolean; submit: (r: unknown) => void }) {
  const situations: { situation_de: string }[] = payload.situations;
  const options: string[] = payload.options;
  const [answers, setAnswers] = useState<(string | null)[]>(situations.map(() => null));
  const allAnswered = answers.every((a) => a !== null);

  return (
    <div>
      <div className="flex flex-col gap-3">
        {situations.map((s, si) => (
          <div key={si} className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2">
            <span className="text-sm"><GermanText text={s.situation_de} /></span>
            <select
              disabled={disabled}
              value={answers[si] ?? ""}
              onChange={(e) => setAnswers((a) => a.map((v, i) => (i === si ? e.target.value : v)))}
              className="rounded-lg border border-line bg-raised px-2 py-1 text-sm outline-none focus:border-gold/50"
            >
              <option value="" disabled>Wählen …</option>
              {options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
            </select>
          </div>
        ))}
      </div>
      {!disabled && (
        <button className="btn-ghost mt-4 w-full" disabled={!allAnswered}
          onClick={() => submit({ options: answers })}>
          Teil abschicken
        </button>
      )}
    </div>
  );
}

function WritingBody({
  payload, disabled, submit,
}: { payload: any; disabled: boolean; submit: (r: unknown) => void }) {
  const isForm = payload.kind === "form";
  const [blanks, setBlanks] = useState<string[]>((payload.blank_labels ?? []).map(() => ""));
  const [text, setText] = useState("");

  return (
    <div>
      <p className="mb-3 text-sm"><GermanText text={payload.scenario_de} /></p>
      {payload.content_points_de?.length > 0 && (
        <ul className="mb-3 list-inside list-disc text-xs text-mute">
          {payload.content_points_de.map((p: string, i: number) => <li key={i}><GermanText text={p} /></li>)}
        </ul>
      )}
      {isForm ? (
        <div className="flex flex-col gap-2">
          {(payload.blank_labels ?? []).map((label: string, i: number) => (
            <div key={i} className="flex items-center gap-3">
              <label className="w-32 shrink-0 text-xs text-mute">{label}</label>
              <input
                disabled={disabled} value={blanks[i]}
                onChange={(e) => setBlanks((b) => b.map((v, idx) => (idx === i ? e.target.value : v)))}
                className="flex-1 rounded-lg border border-line bg-raised px-3 py-1.5 text-sm outline-none focus:border-gold/50 disabled:opacity-70"
              />
            </div>
          ))}
        </div>
      ) : (
        <textarea
          disabled={disabled} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={`~${payload.words ?? 40} Wörter …`} rows={6}
          className="w-full resize-none rounded-xl border border-line bg-raised px-3 py-2 text-sm outline-none focus:border-gold/50 disabled:opacity-70"
        />
      )}
      {!disabled && (
        <button
          className="btn-ghost mt-4 w-full"
          disabled={isForm ? blanks.some((b) => !b.trim()) : !text.trim()}
          onClick={() => submit(isForm ? { answers: blanks } : { text })}
        >
          Teil abschicken
        </button>
      )}
    </div>
  );
}

// -- Sprechen: reuses the same voice pipeline as Sprechen.tsx, simplified
// (no scenario picker — the conv_id already exists once the module starts).

type Turn = { id: string; role: "user" | "assistant"; text: string };

function ExamSpeaking({
  examId, convId, label, onBack, onFinished,
}: { examId: string; convId: string; label: string; onBack: () => void; onFinished: (e: ExamState) => void }) {
  const [connected, setConnected] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [liveAssistant, setLiveAssistant] = useState("");
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<VoiceSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playerRef = useRef<ChunkedPlayer | null>(null);
  const micStopRef = useRef<(() => void) | null>(null);
  const lastSrRef = useRef<number | null>(null);
  const liveAssistantRef = useRef("");

  useEffect(() => {
    liveAssistantRef.current = liveAssistant;
  }, [liveAssistant]);

  useEffect(() => {
    connect();
    return () => cleanup();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convId]);

  function cleanup() {
    micStopRef.current?.();
    micStopRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }

  async function connect() {
    setError(null);
    try {
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const player = new ChunkedPlayer(ctx);
      playerRef.current = player;

      const ws = new VoiceSocket(convId, handleEvent, (data) => {
        const sr = lastSrRef.current ?? 22050;
        player.enqueuePcm16(data, sr);
      });
      wsRef.current = ws;

      const mic = await startMicCapture(ctx, (frame) => ws.sendPcm(frame));
      micStopRef.current = mic.stop;
      setConnected(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleEvent(e: VoiceEvent) {
    switch (e.t) {
      case "stt_final":
        setTurns((t) => [...t, { id: e.turn_id, role: "user", text: e.text }]);
        break;
      case "llm_delta":
        setLiveAssistant((prev) => prev + e.text);
        break;
      case "tts_begin":
        lastSrRef.current = e.sr;
        break;
      case "tts_end":
        setTurns((t) => [...t, { id: e.turn_id, role: "assistant", text: liveAssistantRef.current }]);
        setLiveAssistant("");
        break;
      case "barge_in":
        playerRef.current?.flush();
        setLiveAssistant("");
        break;
      case "error":
        setError(e.message);
        break;
    }
  }

  async function finish() {
    setFinishing(true);
    cleanup();
    try {
      const state = await api<ExamState>(`/api/exams/${examId}/finish-speaking`, { method: "POST" });
      onFinished(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setFinishing(false);
    }
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button className="btn-ghost !p-2" onClick={onBack} aria-label="Zurück"><Icon name="arrowRight" size={16} className="rotate-180" /></button>
          <h1 className="text-lg font-semibold">{label}</h1>
        </div>
        <button className="btn-gold" disabled={!connected || finishing} onClick={finish}>
          {finishing ? "Wird bewertet …" : "Fertig"}
        </button>
      </div>

      {error && <p className="mb-3 text-sm text-ember">{error}</p>}

      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        <AnimatePresence initial={false}>
          {turns.map((t) => (
            <motion.div
              key={t.id + t.role} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${t.role === "user" ? "bg-gold/10 text-ink" : "bg-white/5"}`}>
                <GermanText text={t.text} />
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
    </div>
  );
}
