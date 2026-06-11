import Link from "next/link";
import { Bot, TrendingUp, Zap, CloudSun } from "lucide-react";

const features = [
  {
    icon: Bot,
    title: "AI that knows your league",
    body: "Connected to your real roster, matchups, and scoring settings — not generic takes.",
  },
  {
    icon: TrendingUp,
    title: "Live NFL data",
    body: "Targets, snap counts, injuries, and trends from nflverse, refreshed automatically.",
  },
  {
    icon: Zap,
    title: "Vegas-grounded analysis",
    body: "Implied team totals and spreads factor into every start/sit call.",
  },
  {
    icon: CloudSun,
    title: "Game-day conditions",
    body: "Wind, rain, and temperature at every stadium — domes included.",
  },
];

export default function Landing() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-green-950 via-green-900 to-gray-950 text-white">
      <div className="mx-auto max-w-5xl px-6 py-24 text-center">
        <h1 className="text-5xl font-extrabold tracking-tight">
          Fantasy Football <span className="text-green-400">AI</span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-green-100/80">
          An AI assistant that knows your fantasy league as well as you do — and
          never forgets to check the injury report.
        </p>
        <div className="mt-10 flex justify-center gap-4">
          <Link
            href="/login"
            className="rounded-lg bg-green-500 px-6 py-3 font-semibold text-green-950 hover:bg-green-400"
          >
            Get started
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-green-500/40 px-6 py-3 font-semibold text-green-100 hover:bg-green-500/10"
          >
            Sign in
          </Link>
        </div>

        <div className="mt-24 grid gap-6 text-left sm:grid-cols-2">
          {features.map((f) => (
            <div
              key={f.title}
              className="rounded-xl border border-white/10 bg-white/5 p-6"
            >
              <f.icon className="h-8 w-8 text-green-400" />
              <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm text-green-100/70">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
