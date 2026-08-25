/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    // Replaced rather than extended: the default Tailwind palette is what
    // makes generic dashboards look generic. Only these tokens exist.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      white: '#ffffff',
      ink: '#111111',
      muted: '#6b7280',
      line: '#e5e7eb',
      wash: '#f9fafb',
      accent: '#1a5c2a',
      'accent-wash': '#f0f7f2',
      safe: '#2ea84a',
      moderate: '#d4882a',
      high: '#c0392b',
    },
    borderRadius: {
      none: '0',
      DEFAULT: '3px',
      sm: '2px',
      md: '4px',
      // Only for status dots, which are circles. Nothing rectangular in this
      // system is allowed to take it -- no pills, no rounded buttons.
      full: '9999px',
    },
    boxShadow: {
      none: 'none',
      // The only shadow in the system.
      card: '0 1px 3px rgba(0,0,0,0.08)',
    },
    fontFamily: {
      sans: [
        'Inter',
        'system-ui',
        '-apple-system',
        'Segoe UI',
        'Roboto',
        'sans-serif',
      ],
      mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
    },
    fontSize: {
      // Fixed scale. Every size in the spec, nothing between.
      '2xs': ['10px', '14px'],
      xs: ['11px', '16px'],
      sm: ['12px', '18px'],
      base: ['13px', '20px'],
      md: ['14px', '20px'],
      lg: ['18px', '24px'],
      xl: ['24px', '30px'],
      '4xl': ['48px', '52px'],
    },
    extend: {
      spacing: {
        sidebar: '240px',
        topbar: '48px',
        header: '56px',
        row: '40px',
      },
      letterSpacing: {
        caps: '0.08em',
      },
    },
  },
  plugins: [],
};
