import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Exercise, ExercisePlayer } from "../components/ExercisePlayer";
import { Icon } from "../components/Icon";
import { SrsReview } from "../components/SrsReview";
import { api } from "../lib/api";

type Topic = { id: string; level: string; week: number; title_de: string; title_en: string };

export default function Lernen() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const srsMode = searchParams.get("mode") === "srs";
  const srsBlockId = searchParams.get("block_id") ?? undefined;
  const [topics, setTopics] = useState<Topic[]>([]);
  const [selected, setSelected] = useState<Topic | null>(null);
  const [blockId, setBlockId] = useState<string | null>(null);
  const [exercises, setExercises] = useState<Exercise[] | null>(null);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scores, setScores] = useState<boolean[]>([]);
  const startedAt = useRef<number>(0);
  const autoStarted = useRef(false);

  useEffect(() => {
    if (srsMode) return;
    api<Topic[]>("/api/grammar/topics").then(setTopics).catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srsMode]);

  useEffect(() => {
    if (srsMode || autoStarted.current || topics.length === 0) return;
    const topicId = searchParams.get("topic_id");
    const block = searchParams.get("block_id");
    if (!topicId) return;
    const topic = topics.find((t) => t.id === topicId);
    if (topic) {
      autoStarted.current = true;
      startLesson(topic, block);
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topics]);

  async function startLesson(topic: Topic, forBlockId: string | null = null) {
    setSelected(topic);
    setBlockId(forBlockId);
    setLoading(true);
    setError(null);
    setExercises(null);
    setScores([]);
    setIndex(0);
    startedAt.current = Date.now();
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
    const newScores = [...scores, correct];
    setScores(newScores);
    setIndex((i) => i + 1);
    if (blockId && exercises && newScores.length >= exercises.length) {
      const minutes = Math.max(1, Math.round((Date.now() - startedAt.current) / 60000));
      api(`/api/plan/blocks/${blockId}/complete`, { json: { minutes_actual: minutes } }).catch(() => {});
    }
  }

  function reset() {
    setSelected(null);
    setBlockId(null);
    setExercises(null);
    setScores([]);
  }

  if (srsMode) {
    return (
      <div>
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Wiederholung</h1>
          <button className="btn-ghost" onClick={() => navigate("/")}><Icon name="x" size={16} /> Beenden</button>
        </div>
        <SrsReview blockId={srsBlockId} onDone={() => navigate("/")} />
      </div>
    );
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
              <ExercisePlayer key={exercises[index].id} exercise={exercises[index]} blockId={blockId ?? undefined} onNext={(r) => next(r.correct)} />
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
