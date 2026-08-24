module.exports = {
  content: ["./src/**/*.{js,jsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["'IBM Plex Sans'", "sans-serif"],
        body: ["Manrope", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      colors: {
        abyss: "#020617",
        // These 3 are now bound to CSS variables that switch with data-mode
        // (see index.css: [data-mode="marinas"] and [data-mode="formalities"]).
        // The old static hex values remain the fallback for the projects mode.
        surface: "rgb(var(--surface-rgb, 15 23 42) / <alpha-value>)",
        raised:  "rgb(var(--raised-rgb, 30 41 59) / <alpha-value>)",
        line:    "rgb(var(--line-rgb, 51 65 85) / <alpha-value>)",
        sonar: "#00f0ff",
        bio: "#39ff14",
        alert: "#ff4a4a",
        amberx: "#fbbf24",
        funder: "#c084fc",
        // Semantic "accent" — RGB channels come from --accent-rgb which switches
        // between projects (cyan) / marinas (red) / formalities (amberx) via [data-mode].
        accent: "rgb(var(--accent-rgb) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
