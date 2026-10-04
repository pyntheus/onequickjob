import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy* and waitFor wait up to 3 s (the default is 1 s): test files run in parallel, and a
// busy machine can take over a second to render a page's first data.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});
