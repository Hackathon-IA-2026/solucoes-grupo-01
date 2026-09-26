import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "~/lib/cn";

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }>(({ className, variant = "secondary", type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-[background-color,color,border-color,transform] active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-50",
      variant === "primary" && "bg-ink text-white hover:bg-accent",
      variant === "secondary" && "border border-line bg-surface text-ink hover:border-accent hover:bg-accent-soft",
      variant === "ghost" && "text-ink-soft hover:bg-accent-soft hover:text-ink",
      className,
    )}
    {...props}
  />
));
Button.displayName = "Button";
