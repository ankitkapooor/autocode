import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#102237",
        slate: { DEFAULT: "#5f6f82" },
        line: "#dce3e8",
        canvas: "#f4f7f7",
        warm: "#f4f1ea",
        panel: "#ffffff",
        navy: "#0b3042",
        marketing: "#071f2c",
        blue: { DEFAULT: "#176f86" },
        teal: { DEFAULT: "#08786e" },
        amber: { DEFAULT: "#a85b0b" },
        danger: "#a33d43"
      },
      boxShadow: {
        panel: "0 1px 2px rgba(15, 31, 55, 0.04), 0 8px 28px rgba(15, 31, 55, 0.05)"
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "IBM Plex Mono", "ui-monospace", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
