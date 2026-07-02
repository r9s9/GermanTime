import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { GermanText } from "./GermanText";
import { Icon } from "./Icon";

type SrsCardData = {
  id: string; kind: string; direction: string; front: string; back: string;
  front_is_de: boolean; back_is_de: boolean; note_de?: string; note_en?: string;
};

const RATINGS: { value: number; label: string; cls: string }[] = [
  { value: 1, label: "Nochmal", cls: "border-ember/40 bg-ember/10 text-ember hover:bg-ember/20" },
  { value: 2, label: "Schwer", cls: "border-line bg-white/5 hover:bg-white/10" },
  { value: 3, label: "Gut", cls: "border-line bg-white/5 hover:bg-white/10" },
  { value: 4, label: "Leicht", cls: "border-mint/40 bg-mint/10 text-mint hover:bg-mint/20" },
];

export function SrsReview({ blockId, onDone }: { blockId?: string; onDone: (reviewed: number) => void }) {
  const [cards, setCards] = useState<SrsCardData[] | null>(null);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const startedAt = useRef(Date.now());
  const cardStartedAt = useRef(Date.now());

  useEffect(() => {
    api<SrsCardData[]>("/api/srs/due?limit=20").then(setCards);
  }, []);

  async function rate(rating: number) {
    if (!cards || submitting) return;
    setSubmitting(true);
    const card = cards[index];
    const elapsed = Date.now() - cardStartedAt.current;
    try {
      await api("/api/srs/review", { json: { card_id: card.id, rating, elapsed_ms: elapsed } });
      if (index + 1 >= cards.length) {
        if (blockId) {
          const minutes = Math.max(1, Math.round((Date.now() - startedAt.current) / 60000));
          api(`/api/plan/blocks/${blockId}/complete`, { json: { minutes_actual: minutes } }).catch(() => {});
        }
        onDone(cards.length);
      } else {
        setIndex((i) => i + 1);
        setRevealed(false);
        cardStartedAt.current = Date.now();
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!cards) return null;

  if (cards.length === 0) {
    return (
      <div className="card flex flex-col items-center gap-2 px-8 py-14 text-center">
        <p className="text-mute">Gerade nichts fällig.</p>
        <button className="btn-ghost mt-2" onClick={() => onDone(0)}>Zurück</button>
      </div>
    );
  }

  const card = cards[index];

  return (
    <div>
      <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-white/5">
        <motion.div className="h-full bg-gold" animate={{ width: `${(index / cards.length) * 100}%` }} />
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={card.id}
          initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.2 }}
          className="card flex min-h-52 flex-col items-center justify-center gap-3 p-8 text-center"
        >
          {card.front_is_de ? <GermanText text={card.front} className="text-2xl" /> : <span className="text-2xl">{card.front}</span>}
          {revealed && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col items-center gap-2">
              <div className="h-px w-24 bg-line" />
              {card.back_is_de ? <GermanText text={card.back} className="text-xl text-mint" /> : <span className="text-xl text-mint">{card.back}</span>}
              {card.note_de && <p className="max-w-sm text-xs text-mute"><GermanText text={card.note_de} /></p>}
            </motion.div>
          )}
        </motion.div>
      </AnimatePresence>

      {!revealed ? (
        <button className="btn-gold mt-4 w-full" onClick={() => setRevealed(true)}>
          Antwort zeigen <Icon name="arrowRight" size={16} />
        </button>
      ) : (
        <div className="mt-4 grid grid-cols-4 gap-2">
          {RATINGS.map((r) => (
            <button key={r.value} disabled={submitting} onClick={() => rate(r.value)}
              className={`rounded-xl border px-2 py-3 text-sm font-medium transition-colors disabled:opacity-50 ${r.cls}`}>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
