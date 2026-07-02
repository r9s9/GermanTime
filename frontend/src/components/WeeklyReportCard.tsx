import { useEffect, useState } from "react";

import { GermanText } from "./GermanText";
import { api } from "../lib/api";

type Report = {
  iso_week: string;
  stats: { minutes: number; xp: number; core_days: number; retention: number | null };
  deltas: { minutes: number | null; xp: number | null; retention: number | null; readiness_days: number | null };
  phoneme_deltas: Record<string, number>;
  summary_de: string;
};

function DeltaBadge({ value, suffix = "" }: { value: number | null; suffix?: string }) {
  if (value === null || value === 0) return null;
  const positive = value > 0;
  return (
    <span className={positive ? "text-mint" : "text-ember"}>
      {" "}({positive ? "+" : ""}{value}{suffix})
    </span>
  );
}

export function WeeklyReportCard() {
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    api<Report>("/api/reports/weekly/latest").then(setReport).catch(() => {});
  }, []);

  if (!report) return null;

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-mute">Wochenbericht</h2>
        <span className="chip">{report.iso_week}</span>
      </div>

      {report.summary_de && (
        <p className="mb-4 text-sm text-ink/90"><GermanText text={report.summary_de} /></p>
      )}

      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-lg font-semibold">
            {report.stats.minutes}
            <DeltaBadge value={report.deltas.minutes} />
          </div>
          <div className="text-[11px] text-mute">Minuten</div>
        </div>
        <div>
          <div className="text-lg font-semibold">
            {report.stats.xp}
            <DeltaBadge value={report.deltas.xp} />
          </div>
          <div className="text-[11px] text-mute">XP</div>
        </div>
        <div>
          <div className="text-lg font-semibold">{report.stats.core_days}/7</div>
          <div className="text-[11px] text-mute">Tage geschafft</div>
        </div>
      </div>

      {report.stats.retention !== null && (
        <div className="mt-3 border-t border-line pt-3 text-xs text-mute">
          Wiederholungsquote: {Math.round(report.stats.retention * 100)}%
          <DeltaBadge value={report.deltas.retention !== null ? Math.round(report.deltas.retention * 100) : null} suffix="%" />
        </div>
      )}

      {Object.keys(report.phoneme_deltas).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {Object.entries(report.phoneme_deltas).map(([p, d]) => (
            <span key={p} className={`chip !text-[11px] ${d > 0 ? "!border-mint/40 !text-mint" : "!border-ember/40 !text-ember"}`}>
              {p} {d > 0 ? "+" : ""}{d}
            </span>
          ))}
        </div>
      )}

      {report.deltas.readiness_days !== null && report.deltas.readiness_days !== 0 && (
        <p className="mt-3 text-xs text-mute">
          Prognose-Datum {report.deltas.readiness_days < 0 ? "früher" : "später"} um {Math.abs(report.deltas.readiness_days)} Tage.
        </p>
      )}
    </div>
  );
}
