import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { client } from "./api/client.gen";
import { installResponseEventInterceptor } from "./lib/responseEventInterceptor";
import { cssVariablesResolver, theme } from "./theme";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles/global.css";

client.setConfig({ baseUrl: "" });

const queryClient = new QueryClient();

// Mutation responses carry an `X-Events` header that mirrors what the
// websocket would have delivered; reading it on the response path lets
// the mutating client invalidate its TanStack caches synchronously
// instead of waiting for the WS roundtrip.
installResponseEventInterceptor(queryClient);

const root = document.getElementById("root");
if (!root) {
  throw new Error("#root element not found");
}

createRoot(root).render(
  <StrictMode>
    <MantineProvider
      theme={theme}
      defaultColorScheme="auto"
      cssVariablesResolver={cssVariablesResolver}
    >
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
