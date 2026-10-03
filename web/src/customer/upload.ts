/** Upload photos to the FileStore (POST /api/files) and return their ids. Needs a session. */
import { toApiError } from "../api/client";

export type FileKind = "request_photo" | "dispute_photo";

export async function uploadPhotos(files: File[], kind: FileKind, related: Record<string, string> = {}): Promise<string[]> {
  const ids: string[] = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    for (const [k, v] of Object.entries(related)) form.append(k, v);
    const res = await globalThis.fetch(new Request(`${window.location.origin}/api/files`, { method: "POST", body: form, credentials: "include" }));
    const body = await res.json().catch(() => undefined);
    if (!res.ok) throw toApiError(res.status, body);
    ids.push((body as { id: string }).id);
  }
  return ids;
}
