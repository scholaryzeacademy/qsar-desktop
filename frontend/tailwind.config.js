/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F6F8F3",
        surface: "#FFFFFF",
        surface2: "#EEF2E8",
        ink: "#10231C",
        inkmut: "#57685D",
        line: "#DCE3D8",
        line2: "#CBD6C3",
        brand: {
          950: "#07231A",
          900: "#0B3B2E",
          800: "#0F4E3B",
          700: "#146C4D",
          600: "#1A8560",
          500: "#1F9D6C",
          400: "#3FB884",
          300: "#7CD1A8",
        },
        lime: "#A8E063",
        amber: "#C9862B",
        clay: "#B2503B",
        slateout: "#93A099",
      },
      fontFamily: {
        display: ["\"Fraunces\"", "ui-serif", "Georgia", "serif"],
        sans: ["\"Inter\"", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["\"IBM Plex Mono\"", "ui-monospace", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(11,59,46,.06), 0 8px 24px -8px rgba(11,59,46,.12)",
        pop: "0 24px 64px -12px rgba(7,35,26,.35)",
      },
      keyframes: {
        pulseDot: {
          "0%, 100%": { opacity: 1, transform: "scale(1)" },
          "50%": { opacity: 0.55, transform: "scale(0.82)" },
        },
        riseIn: {
          "0%": { opacity: 0, transform: "translateY(6px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        spinLattice: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
      },
      animation: {
        pulseDot: "pulseDot 1.8s ease-in-out infinite",
        riseIn: "riseIn .25s ease-out",
        spinLattice: "spinLattice 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};
