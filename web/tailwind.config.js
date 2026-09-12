/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Pit-wall console palette. Dark, low-chroma, numbers carry the colour.
        ink: {
          950: "#050507", // page, one step below the old floor so panels lift
          900: "#08080a",
          800: "#0e0e11", // panel
          700: "#16161a", // raised panel
          600: "#1f1f25", // border
          500: "#2c2c34", // strong border
        },
        fg: {
          DEFAULT: "#f2f2f5", // primary text
          dim: "#a8a8b2", // labels -- lifted from #9a9aa4 for contrast at size
          faint: "#6b6b76", // axis ticks, gridlines
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
      // A REAL RAMP.
      //
      // The screen measured 46 elements at 11px and 33 at 12px, then jumped
      // straight to 48px with nothing between. That is two sizes and an
      // outlier, not a scale: the eye has nowhere to go, and at 11px nobody
      // reads it across a room. These steps are roughly 1.25x apart so
      // hierarchy is decided by choosing a step rather than by nudging pixels.
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.06em" }], // 11 - ticks only
        tiny: ["0.8125rem", { lineHeight: "1.15rem" }], // 13 - dense support
        base: ["0.9375rem", { lineHeight: "1.4rem" }], // 15 - body, was 12
        lg: ["1.125rem", { lineHeight: "1.5rem" }], // 18 - panel values
        xl: ["1.5rem", { lineHeight: "1.7rem" }], // 24 - secondary readouts
        "2xl": ["2rem", { lineHeight: "2.1rem" }], // 32 - section headline
        "4xl": ["3rem", { lineHeight: "3rem" }], // 48
        hero: ["5.5rem", { lineHeight: "1", letterSpacing: "-0.03em" }], // 88 - the call
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.8)",
        // The hero panel sits above everything else in the stack, so it gets a
        // lift the other panels do not.
        hero: "0 1px 0 0 rgba(255,255,255,0.05) inset, 0 24px 64px -24px rgba(0,0,0,0.95)",
        glow: "0 0 0 1px rgba(225,6,0,0.25), 0 0 32px -8px rgba(225,6,0,0.25)",
      },
      transitionTimingFunction: {
        // One easing for everything that moves, so motion reads as a system.
        instrument: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      keyframes: {
        "value-in": {
          "0%": { opacity: "0", transform: "translateY(0.35em)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        pulse_ring: {
          "0%": { boxShadow: "0 0 0 0 rgba(225,6,0,0.45)" },
          "70%": { boxShadow: "0 0 0 14px rgba(225,6,0,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(225,6,0,0)" },
        },
      },
      animation: {
        "value-in": "value-in 260ms cubic-bezier(0.2,0.8,0.2,1)",
        // Indeterminate progress for a request in flight. Honest: it says
        // "working", not "23% done", because we do not know.
        sweep: "sweep 1.1s cubic-bezier(0.4,0,0.6,1) infinite",
        flip: "pulse_ring 620ms cubic-bezier(0.2,0.8,0.2,1)",
      },
    },
  },
  plugins: [],
};
