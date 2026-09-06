import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        green: {
          50: "#edf5f0",
          100: "#dcece1",
          200: "#bad9c5",
          300: "#90bf9f",
          400: "#68a980",
          500: "#398559",
          600: "#236c46",
          700: "#195638",
          800: "#17452f",
          900: "#153b2a",
          950: "#10291f",
        },
        field: {
          50: "#f0fdf4",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
        },
      },
    },
  },
  plugins: [],
};

export default config;
