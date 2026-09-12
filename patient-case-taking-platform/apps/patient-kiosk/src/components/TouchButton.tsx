"use client";

import { ButtonHTMLAttributes, ReactNode, useRef } from "react";

interface TouchButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "success" | "danger";
  size?: "small" | "medium" | "large";
  children: ReactNode;
  audioFeedback?: boolean;
}

const VARIANTS = {
  primary: "bg-primary text-white hover:bg-primary/90 active:bg-primary/80",
  secondary: "bg-gray-200 text-primary hover:bg-gray-300 active:bg-gray-400",
  success: "bg-accent text-white hover:bg-accent/90 active:bg-accent/80",
  danger: "bg-red-600 text-white hover:bg-red-700 active:bg-red-800",
};

const SIZES = {
  small: "min-h-[44px] min-w-[44px] px-4 py-2 text-base",
  medium: "min-h-[56px] min-w-[56px] px-6 py-3 text-lg",
  large: "min-h-[64px] min-w-[64px] px-8 py-4 text-xl",
};

export function TouchButton({
  variant = "primary",
  size = "medium",
  children,
  audioFeedback = true,
  className = "",
  onClick,
  ...props
}: TouchButtonProps) {
  const btnRef = useRef<HTMLButtonElement>(null);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (audioFeedback) {
      if (navigator.vibrate) navigator.vibrate(10);
    }
    onClick?.(e);
  };

  return (
    <button
      ref={btnRef}
      className={`
        inline-flex items-center justify-center rounded-xl font-semibold
        transition-all duration-150 ease-out
        focus:outline-none focus:ring-4 focus:ring-accent/50
        disabled:pointer-events-none disabled:opacity-40
        select-none touch-manipulation
        ${VARIANTS[variant]} ${SIZES[size]} ${className}
      `}
      onClick={handleClick}
      {...props}
    >
      {children}
    </button>
  );
}
