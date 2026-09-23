import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

/** Semantic tokens resolve to CSS variables in globals.css so light/dark
 * swap in one place. `accent` is the single brand hue (scrimmage-line blue);
 * `green` is kept purely for positive/semantic states (wins, gains, healthy). */
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        gray: colors.zinc,
        green: colors.emerald,
        accent: {
          DEFAULT: token("accent"),
          hover: token("accent-hover"),
          soft: token("accent-soft"),
          line: token("accent-line"),
          ink: token("accent-ink"),
          fg: token("accent-fg"),
        },
        signal: token("signal"),
        canvas: token("canvas"),
        surface: token("surface"),
        ink: token("ink"),
        muted: token("muted"),
        line: token("line"),
      },
      boxShadow: {
        card: "0 0 0 1px rgb(var(--line)), 0 1px 2px rgb(0 0 0 / 0.04), 0 4px 12px -4px rgb(0 0 0 / 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
