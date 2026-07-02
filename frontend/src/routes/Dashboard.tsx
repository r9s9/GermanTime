import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { GoalRing } from "../components/GoalRing";
import { Icon } from "../components/Icon";
import { api } from "../lib/api";

type Block = {
  id: string; slot: "required" | "stretch"; type: string;
  params: { topic_id: string; level: string; title_de: string; title_en: string };
  status: string; minutes_est: number;
};
type PlanDay = { date: string; syllabus_week: number; core_done: boolean; minutes_done: number; blocks: Block[] };
type Projection = {
  overall_theta: number; cefr: string; projected_date: string | null; goal_date: string;
  slipping: boolean; required_minutes_per_day: number | null;
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" });
}

function BlockRow({ block, onStart }: { block: Block; onStart: (b: Block) => void }) {
  const done = block.status === "done";
  return (
    <button
      onClick={() => !done && onStart(block)}
      disabled={done}
      className={`card flex w-full items-center gap-4 px-4 py-3 text-left transition-colors ${
        done ? "opacity-50" : "hover:bg-white/5"
      }`}
    >
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${done ? "bg-mint/15 text-mint" : "bg-white/5 text-mute"}`}>
        <Icon name={done ? "check" : "book"} size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{block.params.title_de}</div>
        <div className="text-xs text-mute">{block.params.level} · ~{block.minutes_est | 0} Min</div>
      </div>
      {!done && <Icon name="play" size={16} className="shrink-0 text-mute" />}
    </button>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [day, setDay] = useState<PlanDay | null>(null);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<PlanDay>("/api/plan/today").then(setDay).catch((e) => setError(String(e)));
    api<Projection>("/api/plan/projection").then(setProjection).catch(() => {});
  }, []);

  function startBlock(block: Block) {
    const params = new URLSearchParams({
      block_id: block.id, topic_id: block.params.topic_id, level: block.params.level,
    });
    navigate(`/lernen?${params.toString()}`);
  }

  if (error) return <p className="text-sm text-ember">{error}</p>;
  if (!day) return null;

  const required = day.blocks.filter((b) => b.slot === "required");
  const stretch = day.blocks.filter((b) => b.slot === "stretch");
  const requiredDone = required.filter((b) => b.status === "done").length;
  const coreProgress = required.length ? requiredDone / required.length : 0;

  return (
    <div>
      <h1 className="text-2xl font-semibold">Heute</h1>
      <p className="mt-1 text-sm text-mute">Woche {day.syllabus_week} von 24</p>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="card flex items-center gap-4 p-5 md:col-span-1">
          <div className="relative shrink-0">
            <GoalRing progress={coreProgress} size={84} />
            <div className="absolute inset-0 flex items-center justify-center text-sm font-semibold">
              {requiredDone}/{required.length}
            </div>
          </div>
          <div>
            <div className="text-sm font-medium">{day.core_done ? "Tagesziel geschafft!" : "Tagesziel"}</div>
            <div className="text-xs text-mute">{Math.round(day.minutes_done)} Minuten heute</div>
          </div>
        </div>

        {projection && (
          <div className="card p-5 md:col-span-2">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-mute">Prüfungs-Bereitschaft</span>
              <span className="chip">{projection.cefr}</span>
            </div>
            {projection.slipping ? (
              <p className="text-sm text-ember">
                Beim aktuellen Tempo wird das Ziel ({fmtDate(projection.goal_date)}) knapp.
                {projection.required_minutes_per_day && (
                  <> Versuche ~{projection.required_minutes_per_day} Min/Tag, um aufzuholen.</>
                )}
              </p>
            ) : (
              <p className="text-sm text-mint">
                Auf Kurs für B1 bis {fmtDate(projection.goal_date)}
                {projection.projected_date && projection.projected_date !== projection.goal_date && (
                  <> (Prognose: {fmtDate(projection.projected_date)})</>
                )}
                .
              </p>
            )}
          </div>
        )}
      </div>

      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-8">
        <h2 className="mb-2 text-sm font-semibold text-mute">Pflichtprogramm</h2>
        <div className="flex flex-col gap-2">
          {required.map((b) => <BlockRow key={b.id} block={b} onStart={startBlock} />)}
        </div>
      </motion.div>

      {stretch.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-mute">Zusätzlich (optional)</h2>
          <div className="flex flex-col gap-2">
            {stretch.map((b) => <BlockRow key={b.id} block={b} onStart={startBlock} />)}
          </div>
        </div>
      )}
    </div>
  );
}
