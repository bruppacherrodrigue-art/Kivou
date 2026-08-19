// Kivou Tailwind preset v1.0 — adapt to the repository's installed Tailwind version.
import type { Config } from "tailwindcss";

const preset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        kivou: {
          ink: "#0F1D18",
          ivory: "#FAF6F1",
          forest: "#234236",
          beige: "#E7DFD3",
          terracotta: "#C56440",
          brass: "#B08D57",
          surface: "#FFFDF9",
          line: "#D9CFC2",
          success: "#2E6A50",
          warning: "#A86B2C",
          danger: "#9A4A3A",
        },
      },
      fontFamily: {
        display: ["Lora", "Georgia", "serif"],
        sans: ["Instrument Sans", "Inter", "Arial", "sans-serif"],
      },
      borderRadius: {
        "k-sm": "10px",
        "k-md": "14px",
        "k-lg": "18px",
        "k-xl": "24px",
      },
      boxShadow: {
        "k-soft": "0 10px 30px -16px rgba(15,29,24,.07)",
        "k-raised": "0 18px 48px -20px rgba(15,29,24,.10)",
      },
      maxWidth: {
        "k-reading": "720px",
        "k-content": "1280px",
        "k-wide": "1440px",
      },
    },
  },
};

export default preset;
