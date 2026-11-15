import type { Metadata } from "next";
import Link from "next/link";
import Brand from "@/components/Brand";

export const metadata: Metadata = {
  title: "Privacy · FFAI",
  description:
    "What Fantasy Football AI and the FFAI Connect for ESPN extension collect, why, and how to remove it.",
};

const UPDATED = "November 14, 2026";
const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "";
const ISSUES_URL = "https://github.com/aaronbarke/fantasy-football-ai/issues";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-7 text-gray-500">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto min-h-screen w-full max-w-2xl px-5 py-10 sm:py-14">
      <div>
        <Brand href="/" />
      </div>
      <p className="eyebrow mt-12">Privacy</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
        What we collect, and why.
      </h1>
      <p className="mt-4 text-sm leading-7 text-gray-500">
        This covers Fantasy Football AI (this site) and its browser extension,
        FFAI Connect for ESPN. Last updated {UPDATED}.
      </p>

      <Section title="The short version">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            We store your account, your connected leagues and your chats so the
            app can work.
          </li>
          <li>
            The extension reads two ESPN cookies, only when you click a button
            on this site, and sends them only to this app.
          </li>
          <li>We don’t sell your data, show ads, or run analytics trackers.</li>
        </ul>
      </Section>

      <Section title="FFAI Connect for ESPN (the browser extension)">
        <p>
          The extension has one job: letting you connect your own private ESPN
          fantasy league without copying cookies out of your browser’s
          developer tools.
        </p>
        <p>
          <strong className="text-ink">What it reads.</strong>{" "}
          Two cookies from espn.com, named <span className="font-mono">espn_s2</span> and{" "}
          <span className="font-mono">SWID</span>. Together they are your ESPN
          sign-in. It reads no other cookies, no browsing history, and nothing
          from any other site.
        </p>
        <p>
          <strong className="text-ink">When.</strong>{" "}
          Only when you click “Find my ESPN leagues” or “Reconnect ESPN” on
          this site. It does nothing in the background, and it does not run on
          any other website. The extension’s own popup only checks whether you
          are signed in to ESPN; it never sees the cookie values.
        </p>
        <p>
          <strong className="text-ink">Where it goes.</strong>{" "}
          The two cookies are sent over HTTPS to this app’s server and nowhere
          else. The server stores them encrypted, attached to your account, and
          uses them for one thing: asking ESPN for your league’s teams,
          rosters, matchups and settings. The app only reads from ESPN. It
          never changes your lineup, makes trades, or touches your ESPN
          account.
        </p>
        <p>
          <strong className="text-ink">What we don’t do.</strong>{" "}
          We don’t sell or share your ESPN sign-in, don’t use it for
          advertising or for anything unrelated to showing you your league, and
          no person reads it. The extension itself stores nothing and contains
          no remotely loaded code.
        </p>
        <p>
          <strong className="text-ink">Removing it.</strong>{" "}
          Disconnecting a league in the app deletes the stored ESPN sign-in for
          that league. You can remove the extension at any time from your
          browser’s extensions page; the app keeps a manual way to connect.
        </p>
      </Section>

      <Section title="What the app stores">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong className="text-ink">Your account:</strong>{" "}
            your email address and a one-way hash of your password. We never
            store the password itself.
          </li>
          <li>
            <strong className="text-ink">Your leagues:</strong>{" "}
            the league and team you connect from Sleeper or ESPN, with their
            rosters, matchups, standings and scoring settings. For a private
            ESPN league, also the encrypted ESPN sign-in described above.
          </li>
          <li>
            <strong className="text-ink">What you do here:</strong>{" "}
            your chat messages with the assistant, the advice it gave, and any
            mock drafts you run.
          </li>
          <li>
            <strong className="text-ink">In your browser:</strong>{" "}
            a sign-in token and a few preferences (such as your selected league
            and light or dark theme), kept in the browser’s local storage. We
            don’t set advertising or tracking cookies.
          </li>
        </ul>
      </Section>

      <Section title="Who else handles it">
        <p>These services process data for the app to run. None of them receive your ESPN sign-in except ESPN itself.</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong className="text-ink">Anthropic</strong>{" "}
            generates the assistant’s answers. When you ask for advice, your
            message and the relevant league details (rosters, matchups,
            projections) are sent to it.
          </li>
          <li>
            <strong className="text-ink">ESPN and Sleeper</strong>{" "}
            are asked for your league’s data, using the league you connected.
          </li>
          <li>
            <strong className="text-ink">Resend</strong>{" "}
            delivers email, such as an alert when a player on your roster is
            injured. It receives your email address and the message.
          </li>
          <li>
            <strong className="text-ink">Vercel and Railway</strong>{" "}
            host the site, the server and the database.
          </li>
        </ul>
      </Section>

      <Section title="Deleting your data">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            Disconnect a league in the app to delete that league’s data and its
            stored ESPN sign-in.
          </li>
          <li>Clear your chat history from the Chat page.</li>
          <li>
            To delete your whole account, or to ask what we hold about you,{" "}
            {CONTACT_EMAIL ? (
              <>
                email{" "}
                <a className="font-medium text-accent hover:underline" href={`mailto:${CONTACT_EMAIL}`}>
                  {CONTACT_EMAIL}
                </a>
                .
              </>
            ) : (
              <>
                open a request on{" "}
                <a
                  className="font-medium text-accent hover:underline"
                  href={ISSUES_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  the project’s GitHub page
                </a>
                . That page is public, so don’t include anything private in it.
              </>
            )}
          </li>
        </ul>
      </Section>

      <Section title="Changes">
        <p>
          If this policy changes, the date at the top changes with it. The app
          is a personal project and is not affiliated with or endorsed by ESPN,
          Sleeper or the NFL.
        </p>
      </Section>

      <p className="mt-12 border-t border-line pt-6 text-sm">
        <Link href="/" className="font-medium hover:text-accent">
          ← Back to Fantasy Football AI
        </Link>
      </p>
    </main>
  );
}
