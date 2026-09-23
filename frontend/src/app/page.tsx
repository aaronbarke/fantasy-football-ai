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
    label: "01 · Every week",
    tone: "tone-blue",
    title: "Build a better lineup.",
    body: "Compare projected points, player matchups, and your bench options in one weekly game plan.",
    href: "/gameplan",
  },
  {
    icon: MessageSquare,
    label: "02 · Every question",
    tone: "tone-violet",
    title: "Talk it through.",
    body: "Ask about your roster, a close start/sit call, or your next opponent. Get an explanation alongside the numbers.",
    href: "/chat",
  },
  {
    icon: Radio,
    label: "03 · Every pick",
    tone: "tone-amber",
    title: "Be ready on the clock.",
    body: "Explore player rankings, follow your draft, and practice your strategy with a mock draft.",
    href: "/draft",
  },
  {
    icon: ArrowLeftRight,
    label: "04 · Every opportunity",
    tone: "tone-emerald",
    title: "Find your next move.",
    body: "Compare players, weigh both sides of a trade, and explore available talent in your league.",
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
            The playbook
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
            Your fantasy season has a lot of moving parts. Bring your roster,
            research, and next decision together with an assistant built around
            your league.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="button-primary !min-h-[44px] !px-5">
              Find your edge
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#playbook" className="button-secondary !min-h-[44px] !px-5">
              Explore the playbook
            </a>
          </div>
          <div className="hero-integrations">
            <span>Bring your league from</span>
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
            <span>Prepared beats predictable.</span>
            <ArrowUpRight className="h-5 w-5" />
          </div>
        </div>
      </section>
      <section id="playbook" className="landing-features">
        <div className="mb-9 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">From draft day to game day</p>
            <h2>
              A little perspective.
              <br />A better next move.
            </h2>
          </div>
          <p className="max-w-xs text-[15px] leading-relaxed text-gray-500">
            The tools to make a call, with the context to understand it.
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
        <p>Make an informed call. Enjoy the game.</p>
        <Link href="/login" className="text-sm font-medium hover:text-accent">
          Open your workspace <span aria-hidden="true">↗</span>
        </Link>
      </footer>
    </main>
  );
}
