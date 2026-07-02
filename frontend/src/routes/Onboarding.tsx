import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { GermanText } from "../components/GermanText";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";

type Item = { id: string; type: string; payload: { prompt_de: string; options: string[] } };
type PlacementState = { status: string; rung: number; rung_label: string; items: Item[] };
type Summary = { placement_theta: number; cefr: string; syllabus_week: number };

const SELF_REPORT = [
  { key: "none", label: "Noch nie", desc: "Ich fange bei null an" },
  { key: "some", label: "Ein bisschen", desc: "Ein paar Wörter kenne ich" },
  { key: "a1", label: "A1", desc: "Grundkenntnisse" },
  { key: "a2", label: "A2", desc: "Ich kann einfache Gespräche führen" },
  { key: "b1", label: "B1", desc: "Ich komme im Alltag zurecht" },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState<"intro" | "test" | "done">("intro");
  const [placementId, setPlacementId] = useState<string | null>(null);
  const [state, setState] = useState<PlacementState | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [itemIdx, setItemIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);

  async function begin(selfReport: string) {
    setBusy(true);
    try {
      const res = await api<{ placement_id: string } & PlacementState>("/api/placement/start", {
        json: { self_report: selfReport },
      });
      setPlacementId(res.placement_id);
      setState(res);
      setItemIdx(0);
      setSelectedIdx(null);
      setStep("test");
    } finally {
      setBusy(false);
    }
  }

  async function answer(index: number) {
    if (!placementId || !state || busy) return;
    setSelectedIdx(index);
    setBusy(true);
    try {
      const item = state.items[itemIdx];
      const res = await api<{ finished: boolean; rung_complete: boolean; state?: PlacementState; summary?: Summary }>(
        `/api/placement/${placementId}/answer`,
        { json: { exercise_id: item.id, response: { index } } },
      );

      if (res.finished && res.summary) {
        setSummary(res.summary);
        setStep("done");
        return;
      }

      if (res.rung_complete && res.state) {
        setState(res.state);
        setItemIdx(0);
      } else {
        setItemIdx((i) => i + 1);
      }
      setSelectedIdx(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center px-6 py-10">
      <AnimatePresence mode="wait">
        {step === "intro" && (
          <motion.div key="intro" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="w-full text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gold/15 text-gold">
              <Icon name="sparkle" size={30} />
            </div>
            <h1 className="text-2xl font-semibold">Willkommen bei GermanTime</h1>
            <p className="mt-2 text-mute">Ein kurzer Einstufungstest (ca. 5-10 Minuten) hilft mir, deinen Plan von Anfang an richtig einzustellen.</p>
            <p className="mt-6 mb-3 text-sm font-medium text-mute">Hast du schon Deutsch gelernt?</p>
            <div className="flex flex-col gap-2">
              {SELF_REPORT.map((o) => (
                <button key={o.key} disabled={busy} onClick={() => begin(o.key)} className="card flex items-center justify-between px-4 py-3 text-left transition-colors hover:bg-white/5 disabled:opacity-50">
                  <span>
                    <span className="block font-medium">{o.label}</span>
                    <span className="block text-xs text-mute">{o.desc}</span>
                  </span>
                  <Icon name="arrowRight" size={16} className="text-mute" />
                </button>
              ))}
            </div>
          </motion.div>
        )}

        {step === "test" && state && state.items[itemIdx] && (
          <motion.div key={`${state.rung}-${itemIdx}`} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="w-full">
            <div className="mb-4 flex items-center justify-between text-xs text-mute">
              <span>Niveau-Test · {state.rung_label}</span>
              <span>Frage {itemIdx + 1} / {state.items.length}</span>
            </div>
            <div className="card p-6">
              <p className="mb-4 text-lg"><GermanText text={state.items[itemIdx].payload.prompt_de} /></p>
              <div className="flex flex-col gap-2">
                {state.items[itemIdx].payload.options.map((opt, i) => (
                  <button
                    key={i}
                    disabled={busy}
                    onClick={() => answer(i)}
                    className={`w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors disabled:cursor-default ${
                      selectedIdx === i ? "border-gold/50 bg-gold/10" : "border-line bg-white/5 hover:bg-white/10"
                    }`}
                  >
                    <GermanText text={opt} />
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {step === "done" && summary && (
          <motion.div key="done" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="card flex w-full flex-col items-center gap-3 px-8 py-14 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-mint/10 text-mint">
              <Icon name="check" size={26} />
            </div>
            <h2 className="text-xl font-semibold">Dein Startniveau: {summary.cefr}</h2>
            <p className="text-mute">Dein Plan beginnt bei Woche {summary.syllabus_week} von 24. Hör- und Sprechtest folgen, sobald du dein erstes Gespräch startest.</p>
            <button className="btn-gold mt-4" onClick={() => navigate("/")}>
              Los geht's! <Icon name="arrowRight" size={16} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
