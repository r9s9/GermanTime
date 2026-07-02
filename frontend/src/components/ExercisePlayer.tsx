import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { api } from "../lib/api";
import { GermanText } from "./GermanText";
import { Icon } from "./Icon";

export type Exercise = {
  id: string;
  type: "mc" | "cloze" | "ordering" | "matching" | "translation" | "dialogue_gap";
  level: string;
  topic_id: string | null;
  payload: Record<string, any>;
};

type GradeResult = { score: number; correct: boolean; detail: Record<string, any> };

export function ExercisePlayer({
  exercise,
  onNext,
}: {
  exercise: Exercise;
  onNext: (result: GradeResult) => void;
}) {
  const [result, setResult] = useState<GradeResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(response: unknown) {
    if (result || submitting) return;
    setSubmitting(true);
    try {
      const r = await api<GradeResult>(`/api/exercises/${exercise.id}/attempt`, { json: { response } });
      setResult(r);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <motion.div
      key={exercise.id}
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -24 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="card p-6"
    >
      <TypeBody exercise={exercise} result={result} submit={submit} />
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mt-5 overflow-hidden"
          >
            <FeedbackPanel type={exercise.type} result={result} />
            <button className="btn-gold mt-4 w-full" onClick={() => onNext(result)}>
              Weiter <Icon name="arrowRight" size={16} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function TypeBody({
  exercise, result, submit,
}: { exercise: Exercise; result: GradeResult | null; submit: (r: unknown) => void }) {
  switch (exercise.type) {
    case "mc":
      return <McBody payload={exercise.payload} result={result} submit={submit} />;
    case "cloze":
      return <ClozeBody payload={exercise.payload} result={result} submit={submit} />;
    case "ordering":
      return <OrderingBody payload={exercise.payload} result={result} submit={submit} />;
    case "matching":
      return <MatchingBody payload={exercise.payload} result={result} submit={submit} />;
    case "translation":
      return <TranslationBody payload={exercise.payload} result={result} submit={submit} />;
    case "dialogue_gap":
      return <DialogueGapBody payload={exercise.payload} result={result} submit={submit} />;
  }
}

function OptionButton({
  label, selected, isCorrect, disabled, onClick,
}: { label: string; selected: boolean; isCorrect: boolean | null; disabled: boolean; onClick: () => void }) {
  let cls = "border-line bg-white/5 hover:bg-white/10";
  if (isCorrect === true) cls = "border-mint/60 bg-mint/10 text-mint";
  else if (isCorrect === false && selected) cls = "border-ember/60 bg-ember/10 text-ember";
  else if (selected) cls = "border-gold/50 bg-gold/10";

  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors disabled:cursor-default ${cls}`}
    >
      <GermanText text={label} />
    </button>
  );
}

function McBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <div>
      <p className="mb-4 text-lg"><GermanText text={payload.prompt_de} /></p>
      <div className="flex flex-col gap-2">
        {payload.options.map((opt: string, i: number) => (
          <OptionButton
            key={i}
            label={opt}
            selected={selected === i}
            isCorrect={result ? (i === result.detail.correct_index ? true : selected === i ? false : null) : null}
            disabled={!!result}
            onClick={() => { setSelected(i); submit({ index: i }); }}
          />
        ))}
      </div>
    </div>
  );
}

function ClozeBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const parts = payload.text_de.split("___");
  return (
    <div>
      <p className="mb-4 text-lg">
        {parts[0]}
        <span className="mx-1 rounded border-b-2 border-gold px-2 font-semibold text-gold">
          {selected ?? "___"}
        </span>
        {parts[1]}
      </p>
      <div className="flex flex-wrap gap-2">
        {payload.choices.map((choice: string, i: number) => (
          <button
            key={i}
            disabled={!!result}
            onClick={() => { setSelected(choice); submit({ answer: choice }); }}
            className={`chip !px-3 !py-1.5 !text-sm transition-colors disabled:cursor-default ${
              result
                ? choice === result.detail.correct_answer ? "!border-mint/60 !bg-mint/10 !text-mint"
                  : choice === selected ? "!border-ember/60 !bg-ember/10 !text-ember" : ""
                : choice === selected ? "!border-gold/50 !bg-gold/10 !text-ink" : "hover:!bg-white/10"
            }`}
          >
            {choice}
          </button>
        ))}
      </div>
    </div>
  );
}

function OrderingBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [pool, setPool] = useState<{ tok: string; used: boolean }[]>(
    payload.tokens.map((t: string) => ({ tok: t, used: false })),
  );
  const built = pool.filter((p) => p.used).map((p) => p.tok);

  function pick(i: number) {
    if (result) return;
    setPool((p) => p.map((item, idx) => (idx === i ? { ...item, used: true } : item)));
  }
  function unpick(builtIdx: number) {
    if (result) return;
    let count = -1;
    setPool((p) => p.map((item) => {
      if (!item.used) return item;
      count++;
      return count === builtIdx ? { ...item, used: false } : item;
    }));
  }

  return (
    <div>
      <p className="mb-1 text-sm text-mute">Bring die Wörter in die richtige Reihenfolge:</p>
      <p className="mb-4 text-xs text-mute">{payload.translation_en}</p>
      <div className="mb-4 flex min-h-12 flex-wrap gap-2 rounded-xl border border-dashed border-line p-3">
        {built.length === 0 && <span className="text-sm text-mute">Wähle unten Wörter aus …</span>}
        {built.map((tok, i) => (
          <motion.button
            layout key={i} onClick={() => unpick(i)}
            className="rounded-lg border border-gold/50 bg-gold/10 px-3 py-1.5 text-sm"
          >
            {tok}
          </motion.button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {pool.map((item, i) => !item.used && (
          <motion.button
            layout key={i} onClick={() => pick(i)}
            className="rounded-lg border border-line bg-white/5 px-3 py-1.5 text-sm hover:bg-white/10"
          >
            {item.tok}
          </motion.button>
        ))}
      </div>
      {!result && (
        <button
          className="btn-ghost mt-4 w-full"
          disabled={built.length !== payload.tokens.length}
          onClick={() => submit({ order: built })}
        >
          Prüfen
        </button>
      )}
    </div>
  );
}

function MatchingBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [pairs, setPairs] = useState<{ left: string; right: string }[]>([]);
  const [pickedLeft, setPickedLeft] = useState<string | null>(null);
  const pairedLefts = new Set(pairs.map((p) => p.left));
  const pairedRights = new Set(pairs.map((p) => p.right));

  function clickLeft(l: string) {
    if (result || pairedLefts.has(l)) return;
    setPickedLeft(l === pickedLeft ? null : l);
  }
  function clickRight(r: string) {
    if (result || pairedRights.has(r) || !pickedLeft) return;
    setPairs((p) => [...p, { left: pickedLeft, right: r }]);
    setPickedLeft(null);
  }
  function unpair(l: string) {
    if (result) return;
    setPairs((p) => p.filter((x) => x.left !== l));
  }

  return (
    <div>
      <p className="mb-4 text-lg"><GermanText text={payload.prompt_de} /></p>
      <div className="mb-4 flex flex-wrap gap-2">
        {pairs.map((p, i) => (
          <span key={i} onClick={() => unpair(p.left)} className="chip cursor-pointer !border-gold/40 !text-ink">
            {p.left} → {p.right}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-2">
          {payload.left.map((l: string) => !pairedLefts.has(l) && (
            <button key={l} onClick={() => clickLeft(l)}
              className={`rounded-lg border px-3 py-2 text-left text-sm ${pickedLeft === l ? "border-gold/60 bg-gold/10" : "border-line bg-white/5 hover:bg-white/10"}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-2">
          {payload.right.map((r: string) => !pairedRights.has(r) && (
            <button key={r} onClick={() => clickRight(r)}
              className="rounded-lg border border-line bg-white/5 px-3 py-2 text-left text-sm hover:bg-white/10">
              {r}
            </button>
          ))}
        </div>
      </div>
      {!result && (
        <button className="btn-ghost mt-4 w-full" disabled={pairs.length !== payload.left.length}
          onClick={() => submit({ pairs })}>
          Prüfen
        </button>
      )}
    </div>
  );
}

function TranslationBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [text, setText] = useState("");
  const isDeToEn = payload.direction === "de_en";
  return (
    <div>
      <p className="mb-1 text-xs uppercase tracking-wide text-mute">
        {isDeToEn ? "Deutsch → Englisch" : "Englisch → Deutsch"}
      </p>
      <p className="mb-3 text-lg">
        {isDeToEn ? <GermanText text={payload.source_text} /> : payload.source_text}
      </p>
      {payload.hint_de && <p className="mb-3 text-xs text-mute">💡 <GermanText text={payload.hint_de} /></p>}
      <textarea
        value={text} onChange={(e) => setText(e.target.value)} disabled={!!result}
        placeholder="Deine Übersetzung …" rows={2}
        className="w-full resize-none rounded-xl border border-line bg-raised px-3 py-2 text-sm outline-none focus:border-gold/50 disabled:opacity-70"
      />
      {!result && (
        <button className="btn-ghost mt-3 w-full" disabled={!text.trim()} onClick={() => submit({ text })}>
          Prüfen
        </button>
      )}
    </div>
  );
}

function DialogueGapBody({ payload, result, submit }: { payload: any; result: GradeResult | null; submit: (r: unknown) => void }) {
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <div>
      <div className="mb-4 flex flex-col gap-2">
        {payload.turns.map((t: { speaker: string; text_de: string | null }, i: number) => (
          <div key={i} className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${i % 2 === 0 ? "self-start bg-white/5" : "self-end bg-gold/10"}`}>
            <span className="mb-0.5 block text-[10px] uppercase tracking-wide text-mute">{t.speaker}</span>
            {t.text_de === null ? <span className="text-gold">___</span> : <GermanText text={t.text_de} />}
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        {payload.options.map((opt: string, i: number) => (
          <OptionButton
            key={i} label={opt} selected={selected === i}
            isCorrect={result ? (i === result.detail.correct_index ? true : selected === i ? false : null) : null}
            disabled={!!result}
            onClick={() => { setSelected(i); submit({ index: i }); }}
          />
        ))}
      </div>
    </div>
  );
}

function FeedbackPanel({ type, result }: { type: Exercise["type"]; result: GradeResult }) {
  const { detail, correct } = result;
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${correct ? "border-mint/40 bg-mint/5 text-mint" : "border-ember/40 bg-ember/5 text-ember"}`}>
      <div className="mb-1 flex items-center gap-2 font-semibold">
        <Icon name={correct ? "check" : "x"} size={16} />
        {correct ? "Richtig!" : "Nicht ganz richtig"}
      </div>
      <div className="text-ink/80">
        {(type === "mc" || type === "cloze") && !correct && (detail.explanation_de || detail.explanation_en) && (
          <p><GermanText text={detail.explanation_de} /> <span className="text-mute">({detail.explanation_en})</span></p>
        )}
        {type === "ordering" && !correct && (
          <p>Richtige Reihenfolge: <GermanText text={detail.correct_tokens.join(" ")} /></p>
        )}
        {type === "matching" && (
          <p>{detail.n_correct} von {detail.n_total} richtig zugeordnet.</p>
        )}
        {type === "translation" && (
          <p>Akzeptiert: {detail.accepted_answers.join(" / ")}{detail.close && !correct ? " (sehr nah dran!)" : ""}</p>
        )}
        {type === "dialogue_gap" && !correct && (
          <p>Richtige Antwort: <GermanText text={detail.correct_text_de} /></p>
        )}
      </div>
    </div>
  );
}
