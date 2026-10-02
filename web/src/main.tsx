import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { makeRouter } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/customer.css";
import "./styles/provider.css";
import "./styles/admin.css";
import "./styles/demo.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: true, retry: 1 },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={makeRouter()} />
    </QueryClientProvider>
  </StrictMode>,
);
