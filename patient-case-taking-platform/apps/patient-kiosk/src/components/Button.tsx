import { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary";
  children: ReactNode;
}

export function Button({ variant = "primary", children, className = "", ...props }: ButtonProps) {
  return (
    <button className={`${buttonClassName(variant)} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function buttonClassName(variant: "primary" | "secondary" = "primary") {
  const base = "inline-flex min-h-[48px] items-center justify-center rounded-lg px-8 text-lg font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50";
  const styles =
    variant === "primary"
      ? "bg-primary text-white hover:bg-primary/90"
      : "bg-gray-200 text-primary hover:bg-gray-300";

  return `${base} ${styles}`;
}
