/**
 * Design tokens extracted from Stitch export.
 * These mirror the Tailwind config and are provided for programmatic use.
 */
export const tokens = {
  colors: {
    primary: "#8359f8",
    bgDark: "#0b0813",
    cardDark: "#151022",
    borderDark: "#2c2839",
    surface: "rgba(21, 16, 34, 0.7)",
  },
  fonts: {
    display: "Inter, sans-serif",
    mono: "JetBrains Mono, monospace",
  },
  radius: {
    sm: "0.5rem",
    lg: "1rem",
    xl: "1.5rem",
    full: "9999px",
  },
} as const;
