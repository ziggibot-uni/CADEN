/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // CADEN palette — low stimulation, dark
        surface: {
          DEFAULT: "#0f0f0f",
          1: "#161616",
          2: "#1e1e1e",
          3: "#272727",
        },
        accent: {
          DEFAULT: "#4a9b8e", // desaturated teal
          dim: "#2d6b61",
          muted: "#1e4a44",
        },
        text: {
          DEFAULT: "#c8c8c8",
          muted: "#7a7a7a",
          dim: "#4a4a4a",
        },
        urgency: {
          high: "#c0392b",
          med: "#b5842a",
          low: "#2d6b61",
        },
      },
      fontFamily: {
        sans: ["'Inter'", "'DM Sans'", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.2s ease-in-out",
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
