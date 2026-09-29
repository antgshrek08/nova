/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Dark charcoal surfaces for the redesigned shell/Chat screen (task:
      // "Dark charcoal surfaces, restrained emerald accents") -- a neutral
      // gray scale, deliberately not Tailwind's slate (which leans blue),
      // paired with Tailwind's stock emerald for accents so no new palette
      // needs inventing for that half. Legacy screens (Code/Workspace/
      // Memory/Settings) keep their existing slate/indigo classes untouched
      // while their own redesigns are pending.
      colors: {
        charcoal: {
          50: "#f5f7f6",
          100: "#e6ebe8",
          200: "#ced6d1",
          950: "#0a0b0c",
          900: "#131416",
          850: "#191b1e",
          800: "#202226",
          700: "#2b2e33",
          600: "#3a3e44",
          500: "#565b62",
          400: "#8b9098",
          300: "#b4b8bd",
        },
      },
    },
  },
  plugins: [],
};
