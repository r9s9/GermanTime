import { motion } from "motion/react";

import { Icon } from "./Icon";

export function StreakFlame({ streak, freezeBank }: { streak: number; freezeBank: number }) {
  const active = streak > 0;
  return (
    <div className="flex items-center gap-2">
      <motion.div
        animate={active ? { scale: [1, 1.12, 1] } : {}}
        transition={{ repeat: Infinity, duration: 1.6 }}
        className={`flex h-9 w-9 items-center justify-center rounded-xl ${active ? "bg-ember/15 text-ember" : "bg-white/5 text-mute"}`}
      >
        <Icon name="flame" size={18} />
      </motion.div>
      <div>
        <div className="text-sm font-semibold leading-tight">{streak} {streak === 1 ? "Tag" : "Tage"}</div>
        <div className="text-[11px] text-mute">
          {freezeBank > 0 ? `${freezeBank} Freeze${freezeBank > 1 ? "s" : ""} gebankt` : "Serie"}
        </div>
      </div>
    </div>
  );
}
