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
        surface: "#0f172a",
        raised: "#1e293b",
        line: "#334155",
        sonar: "#00f0ff",
        bio: "#39ff14",
        alert: "#ff4a4a",
        amberx: "#fbbf24",
        funder: "#c084fc",
      },
    },
  },
  plugins: [],
};
