export type ButtonVariant = "primary" | "cta" | "ghost" | "link" | "plain";
export type ButtonSize = "lg" | "sm" | "md";
export type ButtonLook = { variant?: ButtonVariant; size?: ButtonSize; block?: boolean; className?: string };

/** The prototype's button classes: "btn btn-cta btn-lg btn-block". */
export function buttonClass({ variant = "plain", size = "md", block, className }: ButtonLook): string {
  return [
    "btn",
    variant !== "plain" && `btn-${variant}`,
    size !== "md" && `btn-${size}`,
    block && "btn-block",
    className,
  ]
    .filter(Boolean)
    .join(" ");
}
