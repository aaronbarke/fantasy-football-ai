import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  ArrowLeftRight,
  ClipboardList,
  MessageSquare,
  Radio,
} from "lucide-react";
import Brand from "@/components/Brand";
import PlaybookField from "@/components/PlaybookField";

const features = [
  {
    icon: ClipboardList,
    label: "01 · Weekly lineups",
    tone: "tone-blue",
    title: "Set your best lineup.",
    body: "Projected points, matchups, and the close start/sit calls for your whole roster, every week.",
    href: "/gameplan",
  },
  {
    icon: MessageSquare,
    label: "02 · Ask anything",
    tone: "tone-violet",
    title: "Ask about your team.",
    body: "Ask about a start/sit call, a trade, or your next opponent. You get an answer and the numbers behind it.",
    href: "/chat",
  },
  {
    icon: Radio,
    label: "03 · Draft day",
    tone: "tone-amber",
    title: "Draft with a plan.",
    body: "Rankings for your scoring settings, a live draft tracker, and mock drafts to practice with.",
    href: "/draft",
  },
  {
    icon: ArrowLeftRight,
    label: "04 · Trades and waivers",
    tone: "tone-emerald",
    title: "Make better trades.",
    body: "Check both sides of a trade, compare players head to head, and find the best free agents in your league.",
    href: "/trade",
  },
];

export default function Landing() {
  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Main navigation">
        <Brand href="/" />
        <div className="flex items-center gap-5">
          <a
            href="#playbook"
            className="hidden text-sm font-medium text-gray-500 hover:text-ink sm:inline"
          >
            Features
          </a>
          <Link href="/login" className="button-secondary">
            Sign in
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>
      </nav>
      <section className="landing-hero">
        <div className="hero-copy">
          <p className="hero-badge">
            <span>2026 season</span>
            Sleeper and ESPN leagues supported
          </p>
          <h1>
            Less second&#8209;guessing.
            <br />
            <span>
              More <mark>game plan.</mark>
            </span>
          </h1>
          <p className="hero-description">
            Connect your league and get lineup advice, start/sit calls, trade
            help, and draft rankings based on your actual roster.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="button-primary !min-h-[44px] !px-5">
              Get started
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#playbook" className="button-secondary !min-h-[44px] !px-5">
              See how it works
            </a>
          </div>
          <div className="hero-integrations">
            <span>Works with</span>
            <strong>Sleeper</strong>
            <span className="h-3 w-px bg-gray-300" />
            <strong>ESPN</strong>
          </div>
        </div>
        <div className="hero-art stage">
          <div className="flex items-center justify-between px-7 pt-7">
            <span className="font-mono text-[11px] tracking-[.14em] text-zinc-400">
              WK 01 · 3RD &amp; 7
            </span>
            <span className="flex items-center gap-2 text-[11px] font-medium text-zinc-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal" />
              Live
            </span>
          </div>
          <PlaybookField />
          <div className="field-caption">
            <span>Know who to start before kickoff.</span>
            <ArrowUpRight className="h-5 w-5" />
          </div>
        </div>
      </section>
      <section id="playbook" className="landing-features">
        <div className="mb-9 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">From draft day to game day</p>
            <h2>
              Help with every decision,
              <br />all season long.
            </h2>
          </div>
          <p className="max-w-xs text-[15px] leading-relaxed text-gray-500">
            Every recommendation comes with the reasons behind it.
          </p>
        </div>
        <div className="feature-grid">
          {features.map((f) => (
            <Link href={f.href} key={f.label} className={`feature-card ${f.tone}`}>
              <div className="flex items-center justify-between">
                <span className="tone-chip h-9 w-9">
                  <f.icon className="h-[18px] w-[18px]" strokeWidth={1.8} />
                </span>
                <ArrowUpRight className="h-4 w-4 text-gray-400" />
              </div>
              <p className="mt-8 font-mono text-[11px] tracking-[.06em] text-gray-500">
                {f.label}
              </p>
              <h3>{f.title}</h3>
              <p className="feature-body">{f.body}</p>
            </Link>
          ))}
        </div>
      </section>
      <footer className="landing-footer">
        <Brand href="/" />
        <p>Make better calls. Enjoy the game.</p>
        <Link href="/login" className="text-sm font-medium hover:text-accent">
          Get started <span aria-hidden="true">↗</span>
        </Link>
      </footer>
    </main>
  );
}
