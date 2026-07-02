import { useEffect, useState } from "react";
import {
  PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer,
} from "recharts";

import { BadgeGrid } from "../components/BadgeGrid";
import { PronProfile } from "../components/PronProfile";
import { WeeklyReportCard } from "../components/WeeklyReportCard";
import { api } from "../lib/api";
import { SKILL_LABELS, SKILL_ORDER } from "../lib/skills";

type Overview = {
  thetas: Record<string, number>;
  overall_theta: number;
  cefr: string;
  vocab_coverage: Record<string, number>;
  grammar_mastered: number;
  grammar_total: number;
};
type Projection = {
  overall_theta: number; cefr: string; target_theta: number; median_daily_minutes: number;
  projected_date: string | null; goal_date: string; slipping: boolean;
  required_minutes_per_day: number | null; data_points: number;
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" });
}

export default function Fortschritt() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projection, setProjection] = useState<Projection | null>(null);

  useEffect(() => {
    api<Overview>("/api/progress/overview").then(setOverview).catch(() => {});
    api<Projection>("/api/plan/projection").then(setProjection).catch(() => {});
  }, []);

  if (!overview) return null;

  const radarData = SKILL_ORDER.map((s) => ({ skill: SKILL_LABELS[s], value: overview.thetas[s] ?? 0 }));

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Fortschritt</h1>
        <span className="chip !text-sm">{overview.cefr} · {overview.overall_theta.toFixed(0)}/100</span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="card p-5">
          <h2 className="mb-2 text-sm font-semibold text-mute">Fähigkeiten</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="75%">
                <PolarGrid stroke="rgba(255,255,255,0.1)" />
                <PolarAngleAxis dataKey="skill" tick={{ fill: "#8d8d9c", fontSize: 11 }} />
                <Radar dataKey="value" stroke="#ffc53d" fill="#ffc53d" fillOpacity={0.25} strokeWidth={2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card p-5">
          <h2 className="mb-3 text-sm font-semibold text-mute">Wortschatz-Abdeckung</h2>
          <div className="flex flex-col gap-3">
            {(["A1", "A2", "B1"] as const).map((lvl) => {
              const pct = (overview.vocab_coverage[lvl] ?? 0) * 100;
              return (
                <div key={lvl}>
                  <div className="mb-1 flex justify-between text-xs text-mute">
                    <span>{lvl}</span>
                    <span>{pct.toFixed(0)}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-white/5">
                    <div className="h-full rounded-full bg-sky" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 border-t border-line pt-4 text-sm">
            <span className="font-medium">{overview.grammar_mastered}</span>
            <span className="text-mute"> von {overview.grammar_total} Grammatikthemen gemeistert</span>
          </div>
        </div>
      </div>

      {projection && (
        <div className="card mt-4 p-5">
          <h2 className="mb-3 text-sm font-semibold text-mute">B1-Prognose</h2>
          {projection.data_points < 4 ? (
            <p className="text-sm text-mute">Noch nicht genug Verlaufsdaten für eine verlässliche Prognose — übe ein paar Tage weiter.</p>
          ) : (
            <p className={`text-sm ${projection.slipping ? "text-ember" : "text-mint"}`}>
              {projection.slipping
                ? `Beim aktuellen Tempo wird das Ziel (${fmtDate(projection.goal_date)}) knapp.`
                : `Auf Kurs für B1 bis ${fmtDate(projection.goal_date)}.`}
              {projection.projected_date && ` Prognose: ${fmtDate(projection.projected_date)}.`}
            </p>
          )}
          <div className="mt-3 flex gap-6 text-xs text-mute">
            <span>Ø {projection.median_daily_minutes} Min/Tag</span>
            <span>Ziel-Niveau: {projection.target_theta}/100</span>
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <WeeklyReportCard />
        <BadgeGrid />
      </div>

      <div className="mt-6">
        <h2 className="mb-3 text-sm font-semibold text-mute">Aussprache</h2>
        <PronProfile />
      </div>
    </div>
  );
}
