import { Camera, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

const ACCEPT = "image/jpeg,image/png,image/webp,image/heic";
const MAX_BYTES = 10 * 1024 * 1024;

/** Up to `max` photos, previewed from the device; the caller uploads them (POST /api/files). */
export function PhotoPicker({
  files,
  onChange,
  max = 4,
  onReject,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  max?: number;
  onReject?: (message: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);

  const add = (picked: FileList | null) => {
    if (!picked) return;
    const ok = Array.from(picked).filter((f) => f.size <= MAX_BYTES);
    if (ok.length < picked.length) onReject?.("Photos can be up to 10 MB each.");
    onChange([...files, ...ok].slice(0, max));
    if (input.current) input.current.value = "";
  };

  return (
    <div className="photo-grid">
      {files.map((f, i) => (
        <div key={`${f.name}-${i}`} className="photo">
          <img src={urls[i]} alt={`Added ${i + 1} of ${files.length}: ${f.name}`} />
          <button
            type="button"
            className="x"
            aria-label={`Remove photo ${i + 1}`}
            onClick={() => onChange(files.filter((_, j) => j !== i))}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
      {files.length < max && (
        <label className="photo-add">
          <Camera size={22} aria-hidden="true" />
          Add photo
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            multiple
            className="sr-only"
            onChange={(e) => add(e.target.files)}
          />
        </label>
      )}
    </div>
  );
}
