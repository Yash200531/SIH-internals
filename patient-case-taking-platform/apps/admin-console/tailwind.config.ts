import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        midnight: "#0a0e1a",
        "midnight-light": "#111827",
        "midnight-border": "#1e293b",
        accent: "#3b82f6",
        "accent-hover": "#2563eb",
        surface: "#1e293b",
      },
    },
  },
  plugins: [],
};

export default config;
