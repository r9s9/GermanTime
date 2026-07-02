import { useEffect, useState } from "react";

import { Icon } from "./Icon";
import { api } from "../lib/api";

type Badge = {
  id: string; name_de: string; name_en: string; desc_de: string; desc_en: string;
  icon: string; awarded: boolean; awarded_at: string | null;
};
type GamifySummary = { badges: Badge[]; badges_earned: number };

export function BadgeGrid() {
  const [data, setData] = useState<GamifySummary | null>(null);

  useEffect(() => {
    api<GamifySummary>("/api/gamify/summary").then(setData).catch(() => {});
  }, []);

  if (!data) return null;

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-mute">Abzeichen</h2>
        <span className="chip">{data.badges_earned}/{data.badges.length}</span>
      </div>
      <div className="grid grid-cols-4 gap-3 sm:grid-cols-5 md:grid-cols-6">
        {data.badges.map((b) => (
          <div key={b.id} className="group relative flex flex-col items-center gap-1.5" title={b.desc_de}>
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-2xl transition-colors ${
                b.awarded ? "bg-gold/15 text-gold" : "bg-white/5 text-mute/40"
              }`}
            >
              <Icon name={b.icon} size={20} />
            </div>
            <span className={`text-center text-[10px] leading-tight ${b.awarded ? "text-ink" : "text-mute/60"}`}>
              {b.name_de}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
