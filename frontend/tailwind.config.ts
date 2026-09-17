import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#13213b",
        slate: { DEFAULT: "#526079" },
        line: "#d9dfe8",
        canvas: "#f4f6f9",
        panel: "#ffffff",
        navy: "#0d2b4d",
        blue: { DEFAULT: "#1e6f9f" },
        teal: { DEFAULT: "#0f7a73" },
        amber: { DEFAULT: "#a95b05" },
        danger: "#a63a3a"
      },
      boxShadow: {
        panel: "0 1px 2px rgba(15, 31, 55, 0.04), 0 8px 28px rgba(15, 31, 55, 0.05)"
      },
      fontFamily: {
        sans: ["Inter", "Avenir Next", "Segoe UI", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "SFMono-Regular", "Consolas", "ui-monospace", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
