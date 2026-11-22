import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    // lib/roles.ts spells out each role's colour classes.
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        slate: {
          400: "#b0bfd2",
          500: "#94a7c0",
          600: "#879bb5",
          700: "#33445e",
          800: "#24334a",
          900: "#111c2e",
          950: "#080e19",
        },
      },
      fontFamily: {
        sans: ["var(--font-plex)", "var(--font-plex-arabic)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
