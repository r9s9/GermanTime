import { useEffect, useState } from "react";

import { PronDrill } from "./PronDrill";
import { api } from "../lib/api";

type PhonemeEntry = {
  phoneme: string; ema: number | null; n: number; weak: boolean;
  last10: number[]; tip_de: string | null; tip_en: string | null;
};
type Group = { name_de: string; phonemes: PhonemeEntry[] };
type Profile = { groups: Group[]; weak_phonemes: string[] };

function tierClass(ema: number | null): string {
  if (ema === null) return "border-line text-mute";
  if (ema >= 80) return "border-mint/40 text-mint";
  if (ema >= 60) return "border-gold/40 text-gold";
  return "border-ember/40 text-ember";
}

export function PronProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [activePhoneme, setActivePhoneme] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  function load() {
    api<Profile>("/api/pron/profile").then(setProfile).catch(() => {});
  }

  function closeDrill() {
    setActivePhoneme(null);
    load(); // refresh EMAs after practicing
  }

  if (!profile) return null;

  return (
    <div className="flex flex-col gap-4">
      {profile.weak_phonemes.length > 0 && (
        <div className="card p-4">
          <div className="mb-2 text-sm font-semibold text-mute">Zum Üben empfohlen</div>
          <div className="flex flex-wrap gap-2">
            {profile.weak_phonemes.map((p) => (
              <button key={p} className="chip !border-ember/40 !text-ember" onClick={() => setActivePhoneme(p)}>
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {activePhoneme && (
        <PronDrill phoneme={activePhoneme} onClose={closeDrill} />
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {profile.groups.map((g) => (
          <div key={g.name_de} className="card p-4">
            <div className="mb-3 text-sm font-semibold text-mute">{g.name_de}</div>
            <div className="flex flex-wrap gap-2">
              {g.phonemes.map((p) => (
                <button
                  key={p.phoneme}
                  onClick={() => setActivePhoneme(p.phoneme)}
                  title={p.tip_de ?? undefined}
                  className={`rounded-lg border px-2.5 py-1.5 font-mono text-sm transition-colors hover:bg-white/5 ${tierClass(p.ema)}`}
                >
                  {p.phoneme}
                  {p.ema !== null && <span className="ml-1.5 text-[10px] opacity-70">{Math.round(p.ema)}</span>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
