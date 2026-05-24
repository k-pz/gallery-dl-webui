import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { withThemeByDataAttribute } from "@storybook/addon-themes";
import type { Preview } from "@storybook/react";
import { cssVariablesResolver, theme } from "../src/theme";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "../src/styles/global.css";

const preview: Preview = {
  parameters: {
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    backgrounds: { disable: true },
  },
  decorators: [
    withThemeByDataAttribute({
      themes: { light: "light", dark: "dark" },
      defaultTheme: "light",
      attributeName: "data-mantine-color-scheme",
    }),
    (Story) => (
      <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver}>
        <Notifications position="top-right" />
        <Story />
      </MantineProvider>
    ),
  ],
};

export default preview;
