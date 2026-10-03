/**
 * The route tree. Owned by F: lanes add routes in their own routes.tsx, which App.tsx
 * composes, so no lane ever edits this file.
 */
import { createBrowserRouter, type RouteObject } from "react-router";
import { adminRoutes } from "./admin/routes";
import { RootLayout } from "./app/RootLayout";
import { page } from "./app/routing";
import { customerRoutes } from "./customer/routes";
import { providerRoutes } from "./provider/routes";

export const routes: RouteObject[] = [
  {
    Component: RootLayout,
    children: [
      customerRoutes,
      providerRoutes,
      adminRoutes,
      { path: "/signin", lazy: page(() => import("./app/SignInPage")) },
      { path: "*", lazy: page(() => import("./app/NotFound")) },
    ],
  },
];

export function makeRouter() {
  return createBrowserRouter(routes);
}
