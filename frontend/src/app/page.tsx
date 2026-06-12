import Link from "next/link";
import {
  ArrowLeftRight,
  Bot,
  ClipboardList,
  CloudSun,
  LineChart,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";

const features = [
  {
    icon: ClipboardList,
    title: "Weekly Game Plan",
    body: "One click builds your optimal lineup, projects your score, and computes win odds against this week's opponent.",
    highlight: true,
  },
  {
    icon: Bot,
    title: "AI that knows your league",
    body: "Connected to your real roster, matchups, and scoring settings — not generic takes. Every call is graded against what actually happened.",
  },
  {
    icon: TrendingUp,
    title: "Projection engine",
    body: "Two seasons of weighted production, defense-vs-position matchups, and Vegas totals — with a floor and ceiling on every player.",
  },
  {
    icon: ArrowLeftRight,
    title: "Trade analyzer",
    body: "0-100 player values, a who-wins score, and AI counters with the exact sweeteners to even a lopsided deal.",
  },
  {
    icon: Zap,
    title: "Betting edge",
    body: "Live line shopping across US sportsbooks — best price on every side, ranked by how much the books disagree.",
  },
  {
    icon: CloudSun,
    title: "Game-day conditions",
    body: "Wind, rain, and temperature at every stadium — domes included — folded into every recommendation.",
  },
];

const stats = [
  { value: "4,200+", label: "players tracked" },
  { value: "2", label: "seasons of weekly stats" },
  { value: "32", label: "defenses ranked by position" },
  { value: "8+", label: "sportsbooks compared" },
];

export default function Landing() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-green-950 via-green-900 to-gray-950 text-white">
      <div className="mx-auto max-w-5xl px-6 py-20 text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-green-500/15 ring-1 ring-green-400/30">
          <Trophy className="h-8 w-8 text-green-400" />
        </div>
        <h1 className="text-5xl font-extrabold tracking-tight sm:text-6xl">
          Fantasy Football <span className="text-green-400">AI</span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-green-100/80">
          Your league, your roster, real data — an AI co-manager that builds your
          lineup, grades your trades, and shows its work on every call.
        </p>
        <div className="mt-10 flex justify-center gap-4">
          <Link
            href="/login"
            className="rounded-lg bg-green-500 px-7 py-3 font-semibold text-green-950 shadow-lg shadow-green-500/25 hover:bg-green-400"
          >
            Get started free
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-green-500/40 px-7 py-3 font-semibold text-green-100 hover:bg-green-500/10"
          >
            Sign in
          </Link>
        </div>

        <div className="mt-16 grid grid-cols-2 gap-6 sm:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label}>
              <p className="text-3xl font-extrabold text-green-400">{s.value}</p>
              <p className="mt-1 text-xs uppercase tracking-wide text-green-100/60">
                {s.label}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-20 grid gap-6 text-left sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <div
              key={f.title}
              className={`rounded-xl border p-6 transition-colors ${
                f.highlight
                  ? "border-green-400/40 bg-green-500/10 hover:bg-green-500/15"
                  : "border-white/10 bg-white/5 hover:bg-white/10"
              }`}
            >
              <f.icon className="h-8 w-8 text-green-400" />
              <h3 className="mt-4 text-lg font-semibold">
                {f.title}
                {f.highlight && (
                  <span className="ml-2 rounded-full bg-green-400/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-green-300">
                    New
                  </span>
                )}
              </h3>
              <p className="mt-2 text-sm text-green-100/70">{f.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-20 flex items-center justify-center gap-2 text-sm text-green-100/50">
          <LineChart className="h-4 w-4" />
          Works with Sleeper and ESPN leagues · Installable as an app
        </div>
      </div>
    </main>
  );
}
