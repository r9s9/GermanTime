import { useState } from "react";

import { isWord, tokenize } from "./GermanText";
import { WordScore } from "../lib/voiceWs";

/** Renders text with per-word pronunciation coloring once async GOP scoring
 * finishes (falls back to plain text before that, or if scoring failed —
 * see pron_hook.py, which is best-effort and doesn't always produce a
 * result). Words are matched to scores positionally: g2p.words_in() and
 * this component's tokenizer both walk the same text left-to-right, so the
 * nth word-like token lines up with the nth score entry.
 */
export function PronCaption({ text, words }: { text: string; words?: WordScore[] }) {
  const tokens = tokenize(text);
  let wordIdx = 0;
  return (
    <span>
      {tokens.map((tok, i) => {
        if (!isWord(tok)) return <span key={i}>{tok}</span>;
        const score = words?.[wordIdx];
        wordIdx += 1;
        return <ScoredWord key={i} text={tok} score={score} />;
      })}
    </span>
  );
}

function tier(score: number): "good" | "ok" | "weak" {
  if (score >= 80) return "good";
  if (score >= 60) return "ok";
  return "weak";
}

const TIER_CLASSES: Record<ReturnType<typeof tier>, string> = {
  good: "decoration-mint/70",
  ok: "decoration-gold/70",
  weak: "decoration-ember/70",
};

function ScoredWord({ text, score }: { text: string; score?: WordScore }) {
  const [open, setOpen] = useState(false);
  if (!score) return <span>{text}</span>;

  const t = tier(score.score);
  return (
    <span
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span className={`cursor-help underline decoration-2 underline-offset-4 ${TIER_CLASSES[t]}`}>
        {text}
      </span>
      {open && (
        <span className="pointer-events-none absolute left-1/2 top-full z-50 mt-1.5 w-max max-w-64 -translate-x-1/2 rounded-lg border border-line bg-raised px-3 py-2 text-xs normal-case shadow-xl">
          <div className="mb-1 flex items-center justify-between gap-3 font-semibold text-ink">
            <span>{text}</span>
            <span className={t === "good" ? "text-mint" : t === "ok" ? "text-gold" : "text-ember"}>
              {Math.round(score.score)}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {score.phones.map((p, i) => (
              <span
                key={i}
                className={`rounded px-1 font-mono text-[11px] ${
                  tier(p.score) === "good" ? "bg-mint/15 text-mint" : tier(p.score) === "ok" ? "bg-gold/15 text-gold" : "bg-ember/15 text-ember"
                }`}
              >
                {p.p}
              </span>
            ))}
          </div>
        </span>
      )}
    </span>
  );
}
