/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Pit-wall console palette. Dark, low-chroma, numbers carry the colour.
        ink: {
          900: "#08080a", // page
          800: "#0e0e11", // panel
          700: "#16161a", // raised panel
          600: "#1f1f25", // border
          500: "#2c2c34", // strong border
        },
        fg: {
          DEFAULT: "#e9e9ec", // primary text
          dim: "#9a9aa4", // labels
          faint: "#5d5d68", // axis ticks, gridlines
        },
        // Deck motif carries into the app.
        brand: "#e10600",
        // Official Pirelli compound colours.
        compound: {
          hard: "#f2f2f2",
          medium: "#ffd500",
          soft: "#ff3b3b",
          inter: "#3ecf5c",
          wet: "#3b7dff",
        },
        signal: {
          good: "#00d68f",
          warn: "#ffb020",
          bad: "#ff4d4d",
        },
      },
      fontFamily: {
        // Every number is monospace. This is the single biggest cue that a
        // dashboard reads as an instrument rather than a web page.
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.06em" }],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.8)",
      },
    },
  },
  plugins: [],
};
