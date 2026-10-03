import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  flat?: boolean;
  stack?: boolean;
  gap?: number;
  as?: "div" | "section" | "article";
  children: ReactNode;
};

/** The prototype's .card; `stack` adds .stack with a gap (the prototype's --g). */
export function Card({ flat, stack, gap, as: Tag = "div", className, style, children, ...rest }: CardProps) {
  const cls = ["card", flat && "flat", stack && "stack", className].filter(Boolean).join(" ");
  const st = gap !== undefined ? ({ "--g": `${gap}px`, ...style } as CSSProperties) : style;
  return (
    <Tag className={cls} style={st} {...rest}>
      {children}
    </Tag>
  );
}
