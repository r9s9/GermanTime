import { useEffect, useState } from "react";

import { api } from "../lib/api";

type Health = {
  ok: boolean;
  python: string;
  torch: { version?: string; cuda?: boolean; device?: string; sm_120?: boolean; error?: string };
  lmstudio: { reachable: boolean; models: string[]; error?: string };
};

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

  useEffect(() => {
    api<Health>("/api/health").then(setHealth).catch((e) => setError(String(e)));
  }, []);

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
    </div>
  );
}
