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
    label: "01 / EVERY WEEK",
    title: "Build a better lineup.",
    body: "Compare projected points, player matchups, and your bench options in one weekly game plan.",
    href: "/gameplan",
  },
  {
    icon: MessageSquare,
    label: "02 / EVERY QUESTION",
    title: "Talk it through.",
    body: "Ask about your roster, a close start/sit call, or your next opponent. Get an explanation alongside the numbers.",
    href: "/chat",
  },
  {
    icon: Radio,
    label: "03 / EVERY PICK",
    title: "Be ready on the clock.",
    body: "Explore player rankings, follow your draft, and practice your strategy with a mock draft.",
    href: "/draft",
  },
  {
    icon: ArrowLeftRight,
    label: "04 / EVERY OPPORTUNITY",
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
            className="hidden text-xs font-semibold sm:inline"
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
          <p className="eyebrow">YOUR LEAGUE. YOUR NEXT ADVANTAGE.</p>
          <h1>
            Less second-guessing.
            <br />
            <span>More game plan.</span>
          </h1>
          <p className="hero-description">
            Your fantasy season has a lot of moving parts. Bring your roster,
            research, and next decision together with an assistant built around
            your league.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="button-primary">
              Find your edge
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#playbook" className="button-secondary">
              Explore the playbook
            </a>
          </div>
          <div className="hero-integrations">
            <span>BRING YOUR LEAGUE</span>
            <strong>Sleeper</strong>
            <span className="h-3 w-px bg-gray-300" />
            <strong>ESPN</strong>
          </div>
        </div>
        <div className="hero-art">
          <div className="flex items-center justify-between px-7 pt-7">
            <span className="text-[10px] font-semibold tracking-[.18em] text-green-200">
              THE FFAI PLAYBOOK
            </span>
            <span className="h-2 w-2 rounded-full bg-lime-200" />
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
          <p className="max-w-xs text-sm leading-7 text-gray-500">
            The tools to make a call, with the context to understand it.
          </p>
        </div>
        <div className="feature-grid">
          {features.map((f) => (
            <Link href={f.href} key={f.label} className="feature-card">
              <div className="flex items-center justify-between">
                <f.icon className="h-5 w-5 text-green-700" strokeWidth={1.6} />
                <ArrowUpRight className="h-4 w-4 text-gray-400" />
              </div>
              <p className="mt-8 text-[9px] font-semibold tracking-[.13em] text-gray-500">
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
        <Link href="/login" className="text-xs font-semibold">
          Open your workspace <span aria-hidden="true">↗</span>
        </Link>
      </footer>
    </main>
  );
}
