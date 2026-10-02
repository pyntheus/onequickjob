export function Avatar({ initials, size = 44 }: { initials: string; size?: number }) {
  return (
    <div className="avatar" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">
      {initials}
    </div>
  );
}
