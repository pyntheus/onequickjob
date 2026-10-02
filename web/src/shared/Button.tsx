import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router";
import { buttonClass, type ButtonLook } from "./button-class";

type Common = ButtonLook & { children: ReactNode };
type AsButton = Common & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> & { to?: undefined };
type AsLink = Common & { to: string; replace?: boolean; "aria-label"?: string; onClick?: () => void };

export type ButtonProps = AsButton | AsLink;

/** The prototype's .btn: <button>, or a router link when `to` is given. */
export function Button(props: ButtonProps) {
  const cls = buttonClass(props);
  if (props.to !== undefined) {
    const { to, replace, children, onClick } = props;
    return (
      <Link to={to} replace={replace} className={cls} aria-label={props["aria-label"]} onClick={onClick}>
        {children}
      </Link>
    );
  }
  const { variant: _v, size: _s, block: _b, className: _c, children, type = "button", ...rest } = props;
  return (
    <button type={type} className={cls} {...rest}>
      {children}
    </button>
  );
}
