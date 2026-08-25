import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bunker: {
          950: "#0f1131",
          900: "#1a1d4e",
          800: "#2b2f5e",
          700: "#444875",
          600: "#6a6f9e",
          muted: "#aeb2c7"
        },
        neon: {
          green: "#0fff4f",
          greenHover: "#4bff69",
          red: "#ff3131",
          yellow: "#ecd906"
        },
        surface: {
          primary: "#1a1d4e",
          secondary: "#2b2f5e",
          danger: "#4b0404",
          success: "#00370f"
        }
      },
      fontFamily: {
        display: ["Poppins", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"]
      }
    }
  },
  plugins: [],
} satisfies Config;
