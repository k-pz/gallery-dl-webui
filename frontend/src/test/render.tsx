import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type RenderOptions, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  options?: RenderOptions & { client?: QueryClient },
) {
  const client = options?.client ?? makeClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <MantineProvider defaultColorScheme="auto">
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </MantineProvider>
  );
  return { client, ...render(ui, { wrapper: Wrapper, ...options }) };
}
