import type { ReactNode } from "react";
import { Link } from "react-router";

const URL_RE = /(https?:\/\/[^\s"<>]+[^\s"<>.,;:!?)])/g;

/** If url is on our public site, the in-app path to open instead (works on any host or tunnel). */
export function toAppPath(url: string, publicBase: string): string | null {
  const base = publicBase.replace(/\/+$/, "");
  if (!base || !url.startsWith(base)) return null;
  const rest = url.slice(base.length);
  if (rest !== "" && !rest.startsWith("/") && !rest.startsWith("?")) return null;
  return rest.startsWith("/") ? rest : "/" + rest;
}

/** Message text with links: ours open in-app with the router, others as plain links. */
export function linkify(text: string, publicBase: string, onNavigate?: () => void): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const path = toAppPath(url, publicBase);
    out.push(
      path ? (
        <Link key={at} to={path} onClick={onNavigate}>
          {url}
        </Link>
      ) : (
        <a key={at} href={url} target="_blank" rel="noreferrer noopener">
          {url}
        </a>
      ),
    );
    last = at + url.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
