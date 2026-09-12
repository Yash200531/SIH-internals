import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        primary: "#1B365D",
        accent: "#2E8540",
        surface: "#F8F9FA",
      },
    },
  },
  plugins: [],
};

export default config;
