import { useEffect, useState } from "react";

import { api } from "../lib/api";

type Health = {
  ok: boolean;
  python: string;
  torch: { version?: string; cuda?: boolean; device?: string; sm_120?: boolean; error?: string };
  lmstudio: { reachable: boolean; models: string[]; error?: string };
};

type Roles = { tutor?: string; fast?: string; embed?: string };
type Vram = { available: boolean; free_gb?: number; total_gb?: number; chatterbox_safe?: boolean; error?: string };
type Settings = { voice_engine: "piper" | "chatterbox"; [key: string]: unknown };

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-line py-3 last:border-0">
      <span className="text-sm text-mute">{label}</span>
      <span className={`text-sm font-medium ${ok === false ? "text-ember" : ok ? "text-mint" : ""}`}>
        {value}
      </span>
    </div>
  );
}

export default function Einstellungen() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roles, setRoles] = useState<Roles>({});
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [vram, setVram] = useState<Vram | null>(null);
  const [savingEngine, setSavingEngine] = useState(false);

  useEffect(() => {
    api<Health>("/api/health").then(setHealth).catch((e) => setError(String(e)));
    api<Roles>("/api/models/roles").then(setRoles).catch(() => {});
    api<Settings>("/api/settings").then(setSettings).catch(() => {});
    api<Vram>("/api/vram").then(setVram).catch(() => {});
  }, []);

  async function assignRole(role: "tutor" | "fast", modelId: string) {
    setSavingRole(role);
    try {
      const updated = await api<Roles>("/api/models/roles", { method: "PUT", json: { [role]: modelId } });
      setRoles(updated);
    } finally {
      setSavingRole(null);
    }
  }

  async function setVoiceEngine(engine: "piper" | "chatterbox") {
    setSavingEngine(true);
    try {
      await api("/api/settings/voice_engine", { method: "PUT", json: { value: engine } });
      setSettings((s) => (s ? { ...s, voice_engine: engine } : s));
    } finally {
      setSavingEngine(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold">Einstellungen</h1>

      <section className="card mt-6 px-6 py-4">
        <h2 className="pb-2 pt-1 text-sm font-semibold text-mute">System</h2>
        {error && <p className="py-3 text-sm text-ember">{error}</p>}
        {!health && !error && <p className="py-3 text-sm text-mute">Lade…</p>}
        {health && (
          <div>
            <Row label="Python" value={health.python} />
            <Row
              label="GPU"
              value={
                health.torch.error
                  ? `Fehler: ${health.torch.error}`
                  : `${health.torch.device ?? "–"} (torch ${health.torch.version})`
              }
              ok={health.torch.cuda}
            />
            <Row
              label="Blackwell (sm_120)"
              value={health.torch.sm_120 ? "aktiv" : "nicht verfügbar"}
              ok={health.torch.sm_120}
            />
            <Row
              label="LM Studio"
              value={
                health.lmstudio.reachable
                  ? `verbunden – ${health.lmstudio.models.length} Modelle`
                  : "nicht erreichbar"
              }
              ok={health.lmstudio.reachable}
            />
            {health.lmstudio.reachable && (
              <div className="flex flex-wrap gap-2 py-3">
                {health.lmstudio.models.map((m) => (
                  <span key={m} className="chip">{m}</span>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {health?.lmstudio.reachable && (
        <section className="card mt-4 px-6 py-4">
          <h2 className="pb-2 pt-1 text-sm font-semibold text-mute">Modellrollen</h2>
          <p className="pb-3 text-xs text-mute">
            Welches lokale Modell übernimmt welche Rolle. Ein starkes Modell für Tutor + Bewertung reicht meist aus.
          </p>
          {(["tutor", "fast"] as const).map((role) => (
            <div key={role} className="flex items-center justify-between border-b border-line py-3 last:border-0">
              <span className="text-sm text-mute">{role === "tutor" ? "Tutor / Bewertung" : "Schnell (Hintergrund)"}</span>
              <select
                className="rounded-lg border border-line bg-raised px-3 py-1.5 text-sm outline-none focus:border-gold/50"
                value={roles[role] ?? ""}
                disabled={savingRole === role}
                onChange={(e) => assignRole(role, e.target.value)}
              >
                <option value="" disabled>Modell wählen…</option>
                {health.lmstudio.models
                  .filter((m) => !m.includes("embed"))
                  .map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
              </select>
            </div>
          ))}
        </section>
      )}

      {settings && (
        <section className="card mt-4 px-6 py-4">
          <h2 className="pb-2 pt-1 text-sm font-semibold text-mute">Sprachausgabe</h2>
          <p className="pb-3 text-xs text-mute">
            Piper ist die Standardstimme (schnell, CPU). Chatterbox klingt natürlicher, ist aber
            deutlich langsamer und braucht mehr GPU-Speicher.
          </p>
          <div className="flex gap-2">
            {(["piper", "chatterbox"] as const).map((engine) => (
              <button
                key={engine}
                disabled={savingEngine}
                onClick={() => setVoiceEngine(engine)}
                className={`flex-1 rounded-xl border px-4 py-3 text-left text-sm transition-colors disabled:opacity-60 ${
                  settings.voice_engine === engine ? "border-gold/50 bg-gold/10" : "border-line bg-white/5 hover:bg-white/10"
                }`}
              >
                <div className="font-medium">{engine === "piper" ? "Piper" : "Chatterbox"}</div>
                <div className="text-xs text-mute">{engine === "piper" ? "~100ms, empfohlen" : "~2-6s, natürlicher"}</div>
              </button>
            ))}
          </div>
          {vram?.available && (
            <p className="mt-3 text-xs text-mute">
              GPU-Speicher frei: {vram.free_gb} / {vram.total_gb} GB
            </p>
          )}
          {vram?.available && vram.chatterbox_safe === false && settings.voice_engine !== "chatterbox" && (
            <p className="mt-2 text-xs text-ember">
              Wenig freier GPU-Speicher — Chatterbox könnte das Tutor-Modell verdrängen. Piper wird empfohlen.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
