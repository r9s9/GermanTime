import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import { Exercise, ExercisePlayer } from "../components/ExercisePlayer";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";

type Topic = { id: string; level: string; week: number; title_de: string; title_en: string };

export default function Lernen() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [selected, setSelected] = useState<Topic | null>(null);
  const [exercises, setExercises] = useState<Exercise[] | null>(null);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scores, setScores] = useState<boolean[]>([]);

  useEffect(() => {
    api<Topic[]>("/api/grammar/topics").then(setTopics).catch((e) => setError(String(e)));
  }, []);

  async function startLesson(topic: Topic) {
    setSelected(topic);
    setLoading(true);
    setError(null);
    setExercises(null);
    setScores([]);
    setIndex(0);
    try {
      const exs = await api<Exercise[]>(
        `/api/lessons/practice-set?topic_id=${encodeURIComponent(topic.id)}&level=${topic.level}&count=6`,
      );
      setExercises(exs);
      // fire-and-forget: warm the cache for what's likely next, so future lessons feel instant
      api(`/api/factory/enqueue-upcoming?from_topic_id=${encodeURIComponent(topic.id)}&n=2`, { method: "POST" }).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function next(correct: boolean) {
    setScores((s) => [...s, correct]);
    setIndex((i) => i + 1);
  }

  function reset() {
    setSelected(null);
    setExercises(null);
    setScores([]);
  }

  if (selected && exercises) {
    const done = index >= exercises.length;
    return (
      <div>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">{selected.title_de}</h1>
            <p className="text-sm text-mute">{selected.title_en} · Niveau {selected.level}</p>
          </div>
          <button className="btn-ghost" onClick={reset}><Icon name="x" size={16} /> Beenden</button>
        </div>

        {!done && (
          <>
            <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-white/5">
              <motion.div className="h-full bg-gold" animate={{ width: `${(index / exercises.length) * 100}%` }} />
            </div>
            <AnimatePresence mode="wait">
              <ExercisePlayer key={exercises[index].id} exercise={exercises[index]} onNext={(r) => next(r.correct)} />
            </AnimatePresence>
          </>
        )}

        {done && (
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="card flex flex-col items-center gap-3 px-8 py-14 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-mint/10 text-mint">
              <Icon name="check" size={26} />
            </div>
            <h2 className="text-xl font-semibold">Lektion abgeschlossen!</h2>
            <p className="text-mute">{scores.filter(Boolean).length} von {scores.length} richtig</p>
            <div className="mt-2 flex gap-3">
              <button className="btn-ghost" onClick={reset}>Andere Lektion</button>
              <button className="btn-gold" onClick={() => startLesson(selected)}>Nochmal üben</button>
            </div>
          </motion.div>
        )}
      </div>
    );
  }

  const byLevel = topics.reduce<Record<string, Topic[]>>((acc, t) => {
    (acc[t.level] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div>
      <h1 className="text-2xl font-semibold">Lernen</h1>
      <p className="mt-1 text-sm text-mute">Wähle ein Grammatikthema für deine nächste Lektion.</p>
      {error && <p className="mt-4 text-sm text-ember">{error}</p>}

      {Object.entries(byLevel).map(([level, ts]) => (
        <div key={level} className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-mute">{level}</h2>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
            {ts.map((t) => (
              <button
                key={t.id}
                disabled={loading}
                onClick={() => startLesson(t)}
                className="card flex flex-col items-start gap-1 px-4 py-3 text-left transition-colors hover:bg-white/5 disabled:opacity-50"
              >
                <span className="text-xs text-mute">Woche {t.week}</span>
                <span className="text-sm font-medium">{t.title_de}</span>
              </button>
            ))}
          </div>
        </div>
      ))}

      {loading && (
        <div className="mt-6 flex items-center gap-3 text-sm text-mute">
          <motion.div
            className="h-4 w-4 rounded-full border-2 border-gold border-t-transparent"
            animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 0.8, ease: "linear" }}
          />
          Übungen werden erstellt … das kann beim ersten Mal etwas dauern.
        </div>
      )}
    </div>
  );
}
