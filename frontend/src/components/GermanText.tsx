import { useRef, useState } from "react";

import { api } from "../lib/api";

type Gloss = { id?: number; lemma: string; pos: string; article: string; gloss_en: string; level?: string; source?: string };

function tokenize(text: string): string[] {
  return text.match(/[\p{L}\p{M}']+|[^\p{L}\p{M}']+/gu) ?? [text];
}

function isWord(tok: string): boolean {
  return /\p{L}/u.test(tok);
}

export function GermanText({ text, className }: { text: string; className?: string }) {
  const tokens = tokenize(text);
  return (
    <span className={className}>
      {tokens.map((tok, i) =>
        isWord(tok) ? (
          <WordSpan key={i} word={tok} sentence={text} />
        ) : (
          <span key={i}>{tok}</span>
        ),
      )}
    </span>
  );
}

function WordSpan({ word, sentence }: { word: string; sentence: string }) {
  const [gloss, setGloss] = useState<Gloss | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const [srsState, setSrsState] = useState<"idle" | "adding" | "added">("idle");
  const timer = useRef<number | undefined>(undefined);

  function onEnter() {
    timer.current = window.setTimeout(async () => {
      setOpen(true);
      if (!gloss && !loading && !failed) {
        setLoading(true);
        try {
          const g = await api<Gloss>("/api/translate/word", {
            json: { word: word.replace(/[.,!?;:]/g, ""), sentence },
          });
          setGloss(g);
        } catch {
          setFailed(true);
        } finally {
          setLoading(false);
        }
      }
    }, 300);
  }

  function onLeave() {
    window.clearTimeout(timer.current);
    setOpen(false);
  }

  async function addToSrs(e: React.MouseEvent) {
    e.stopPropagation();
    if (!gloss?.id || srsState !== "idle") return;
    setSrsState("adding");
    try {
      await api("/api/srs/add-vocab", { json: { vocab_id: gloss.id, direction: "de_en" } });
      setSrsState("added");
    } catch {
      setSrsState("idle");
    }
  }

  async function playAudio(e: React.MouseEvent) {
    e.stopPropagation();
    if (!gloss) return;
    try {
      const res = await api<{ url: string }>("/api/tts", { json: { text: gloss.lemma, engine: "piper" } });
      new Audio(res.url).play();
    } catch {
      /* silently ignore — non-critical UX enhancement */
    }
  }

  return (
    <span className="relative" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <span className="cursor-help border-b border-dotted border-mute/40 transition-colors hover:border-gold/60 hover:text-gold">
        {word}
      </span>
      {open && (
        <span className="pointer-events-auto absolute left-1/2 top-full z-50 mt-1.5 w-max max-w-56 -translate-x-1/2 rounded-lg border border-line bg-raised px-3 py-2 text-xs normal-case shadow-xl">
          {loading && <span className="text-mute">Lädt …</span>}
          {failed && <span className="text-ember">Übersetzung nicht verfügbar</span>}
          {gloss && (
            <>
              <div className="flex items-center gap-1.5 font-semibold text-ink">
                <button onClick={playAudio} className="text-mute hover:text-gold" aria-label="Aussprache anhören">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M7 4.5v15l13-7.5L7 4.5Z" />
                  </svg>
                </button>
                {gloss.article && <span className="text-gold">{gloss.article} </span>}
                {gloss.lemma}
              </div>
              <div className="text-mute">{gloss.gloss_en}</div>
              {gloss.source === "vocab" && (
                <button
                  onClick={addToSrs}
                  disabled={srsState !== "idle"}
                  className={`mt-1.5 text-[11px] font-medium ${srsState === "added" ? "text-mint" : "text-gold hover:underline"}`}
                >
                  {srsState === "added" ? "✓ Zur Wiederholung hinzugefügt" : "+ Zur Wiederholung"}
                </button>
              )}
            </>
          )}
        </span>
      )}
    </span>
  );
}
