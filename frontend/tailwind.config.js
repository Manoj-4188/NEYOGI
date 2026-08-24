/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // NEYOGI palette.
        forest: {
          DEFAULT: '#1B3B2B',
          50: '#EAF0EC',
          100: '#CBDBD2',
          700: '#25503A',
          900: '#12281D',
        },
        sage: {
          DEFAULT: '#4E8752',
          100: '#DCE8DD',
          200: '#B9D1BB',
          600: '#417046',
        },
        terracotta: {
          DEFAULT: '#C45A37',
          100: '#F5DED6',
          200: '#E8BCAB',
          600: '#A44827',
        },
        parchment: {
          DEFAULT: '#F4F6F0',
          200: '#E7EBE0',
          300: '#D6DCCB',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(27, 59, 43, 0.06), 0 8px 24px rgba(27, 59, 43, 0.08)',
      },
    },
  },
  plugins: [],
};
