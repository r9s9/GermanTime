import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { Icon } from "./components/Icon";
import { api } from "./lib/api";
import Dashboard from "./routes/Dashboard";
import Einstellungen from "./routes/Einstellungen";
import Fortschritt from "./routes/Fortschritt";
import Lernen from "./routes/Lernen";
import Onboarding from "./routes/Onboarding";
import Pruefung from "./routes/Pruefung";
import Sprechen from "./routes/Sprechen";

const nav = [
  { to: "/", label: "Heute", icon: "home" },
  { to: "/sprechen", label: "Sprechen", icon: "mic" },
  { to: "/lernen", label: "Lernen", icon: "book" },
  { to: "/pruefung", label: "Prüfung", icon: "exam" },
  { to: "/fortschritt", label: "Fortschritt", icon: "chart" },
];

function OnboardingGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState<boolean | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api<{ has_placement: boolean }>("/api/progress/overview")
      .then((r) => {
        if (!r.has_placement) {
          navigate("/onboarding", { replace: true });
        } else {
          setReady(true);
        }
      })
      .catch(() => setReady(true)); // fail open — never trap the user on a backend hiccup
  }, [navigate]);

  if (!ready) return null;
  return <>{children}</>;
}

function AppShell() {
  const location = useLocation();
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-surface/60 backdrop-blur">
        <div className="flex items-center gap-2 px-5 pb-4 pt-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gold/15 text-gold">
            <Icon name="sparkle" size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">GermanTime</div>
            <div className="text-[11px] text-mute">Dein Weg zu B1</div>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                  isActive ? "text-ink" : "text-mute hover:text-ink hover:bg-white/5"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-xl bg-white/8 border border-line"
                      transition={{ type: "spring", stiffness: 500, damping: 38 }}
                    />
                  )}
                  <span className="relative z-10 flex items-center gap-3">
                    <Icon name={n.icon} size={18} />
                    {n.label}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 pb-5">
          <NavLink
            to="/einstellungen"
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                isActive ? "bg-white/8 text-ink" : "text-mute hover:text-ink hover:bg-white/5"
              }`
            }
          >
            <Icon name="gear" size={18} />
            Einstellungen
          </NavLink>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="mx-auto max-w-5xl px-8 py-8"
          >
            <Routes location={location}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/sprechen" element={<Sprechen />} />
              <Route path="/lernen" element={<Lernen />} />
              <Route path="/pruefung" element={<Pruefung />} />
              <Route path="/fortschritt" element={<Fortschritt />} />
              <Route path="/einstellungen" element={<Einstellungen />} />
            </Routes>
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  if (location.pathname === "/onboarding") {
    return <Onboarding />;
  }
  return (
    <OnboardingGate>
      <AppShell />
    </OnboardingGate>
  );
}
