import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        rice: {
          navy:    '#00205B',
          blue:    '#5B8DB8',
          gold:    '#C5A028',
          slate:   '#4A5568',
          muted:   '#718096',
          border:  '#E2E8F0',
          surface: '#F7F9FC',
          white:   '#FFFFFF',
        },
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
export default config;
