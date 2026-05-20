import {
  Anchor,
  Badge,
  Button,
  Card,
  type CSSVariablesResolver,
  createTheme,
  Divider,
  Loader,
  type MantineColorsTuple,
  Paper,
  rem,
  Tabs,
  TextInput,
  Title,
} from "@mantine/core";

const amber: MantineColorsTuple = [
  "#fbf6ec",
  "#f3e6c8",
  "#ead29c",
  "#dfbc6f",
  "#d3a64a",
  "#c89134",
  "#b07a2b",
  "#8d6121",
  "#6b491a",
  "#4a3212",
];

const ink: MantineColorsTuple = [
  "#f6f3ee",
  "#ebe6dc",
  "#d2cbbe",
  "#aba391",
  "#807866",
  "#5a5343",
  "#3e3829",
  "#2a251a",
  "#1a160e",
  "#0e0c07",
];

const sansStack =
  '"IBM Plex Sans", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
const serifStack = '"Fraunces", "IBM Plex Serif", Georgia, "Times New Roman", serif';
const monoStack =
  '"IBM Plex Mono", ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, monospace';

export const theme = createTheme({
  fontFamily: sansStack,
  fontFamilyMonospace: monoStack,
  primaryColor: "amber",
  primaryShade: { light: 6, dark: 4 },
  defaultRadius: "md",
  cursorType: "pointer",
  autoContrast: true,
  fontSmoothing: true,
  white: "#fbf7f0",
  black: "#1a160e",
  colors: { amber, ink },
  headings: {
    fontFamily: serifStack,
    fontWeight: "500",
    textWrap: "balance",
    sizes: {
      h1: { fontSize: rem(36), lineHeight: "1.1", fontWeight: "500" },
      h2: { fontSize: rem(26), lineHeight: "1.2", fontWeight: "500" },
      h3: { fontSize: rem(20), lineHeight: "1.3", fontWeight: "500" },
      h4: { fontSize: rem(17), lineHeight: "1.35", fontWeight: "600" },
      h5: { fontSize: rem(15), lineHeight: "1.4", fontWeight: "600" },
    },
  },
  components: {
    Card: Card.extend({
      defaultProps: {
        radius: "md",
        withBorder: true,
        padding: "lg",
      },
      classNames: { root: "app-surface" },
    }),
    Paper: Paper.extend({
      defaultProps: { radius: "md", withBorder: true },
      classNames: { root: "app-surface" },
    }),
    Badge: Badge.extend({
      defaultProps: { radius: "sm", variant: "light", size: "sm" },
    }),
    Button: Button.extend({
      defaultProps: { radius: "md" },
    }),
    Title: Title.extend({
      defaultProps: { fw: 500 },
    }),
    Anchor: Anchor.extend({
      defaultProps: { underline: "hover" },
    }),
    TextInput: TextInput.extend({
      defaultProps: { radius: "md" },
    }),
    Divider: Divider.extend({
      defaultProps: { color: "var(--app-border-subtle)" },
    }),
    Loader: Loader.extend({
      defaultProps: { type: "dots" },
    }),
    Tabs: Tabs.extend({
      defaultProps: { variant: "default" },
    }),
  },
});

/**
 * Per-color-scheme surface tokens. The `--app-*` variables are read by our
 * global stylesheet (styles/global.css) and by inline styles in components
 * that want to opt out of Mantine defaults (e.g. monospaced URL strips).
 */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {
    "--app-mono": monoStack,
    "--app-serif": serifStack,
  },
  light: {
    "--app-bg": "#f7f2e8",
    "--app-bg-elevated": "#fbf7ee",
    "--app-surface": "#ffffff",
    "--app-surface-muted": "#f1ebde",
    "--app-border": "rgba(46, 36, 18, 0.14)",
    "--app-border-subtle": "rgba(46, 36, 18, 0.08)",
    "--app-text": "#1a160e",
    "--app-text-muted": "#5a5343",
    "--app-text-faint": "#807866",
    "--app-accent": amber[6],
    "--app-shadow": "0 1px 0 rgba(46, 36, 18, 0.04), 0 12px 28px -22px rgba(46, 36, 18, 0.25)",
    "--mantine-color-body": "#f7f2e8",
    "--mantine-color-text": "#1a160e",
    "--mantine-color-dimmed": "#5a5343",
    "--mantine-color-default-border": "rgba(46, 36, 18, 0.14)",
  },
  dark: {
    "--app-bg": "#16130d",
    "--app-bg-elevated": "#1d1912",
    "--app-surface": "#1f1b14",
    "--app-surface-muted": "#27221a",
    "--app-border": "rgba(214, 198, 168, 0.14)",
    "--app-border-subtle": "rgba(214, 198, 168, 0.07)",
    "--app-text": "#ebe4d3",
    "--app-text-muted": "#9d9582",
    "--app-text-faint": "#6f6859",
    "--app-accent": amber[4],
    "--app-shadow": "0 1px 0 rgba(0, 0, 0, 0.35), 0 18px 40px -28px rgba(0, 0, 0, 0.55)",
    "--mantine-color-body": "#16130d",
    "--mantine-color-text": "#ebe4d3",
    "--mantine-color-dimmed": "#9d9582",
    "--mantine-color-default-border": "rgba(214, 198, 168, 0.14)",
  },
});
