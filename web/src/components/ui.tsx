import { AlertCircle, CheckCircle2, ChevronDown, Info, Loader2, TriangleAlert } from "lucide-react";
import { useId, useState, type ButtonHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-teal text-white hover:bg-teal-hover disabled:bg-[#9cbfbb] disabled:text-white",
  secondary: "bg-surface text-navy border border-line-strong hover:bg-page disabled:text-muted",
  ghost: "text-teal hover:bg-teal-soft disabled:text-muted",
  danger: "bg-danger text-white hover:bg-[#912018]",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-sm";
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex min-h-9 items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:cursor-not-allowed ${sizing} ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Card({ children, className = "", as: Tag = "section", ...rest }: { children: ReactNode; className?: string; as?: "section" | "div" | "article"; "aria-labelledby"?: string }) {
  return (
    <Tag {...rest} className={`rounded-[var(--radius-card)] border border-line bg-surface ${className}`}>
      {children}
    </Tag>
  );
}

type Tone = "info" | "warning" | "error" | "success";
const TONES: Record<Tone, { box: string; icon: ReactNode }> = {
  info: { box: "border-line bg-page text-ink", icon: <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-muted" /> },
  warning: { box: "border-[#f0d9a8] bg-amber-soft text-[#5c3d00]", icon: <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber" /> },
  error: { box: "border-[#f5c2bd] bg-danger-soft text-[#7a1a12]", icon: <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" /> },
  success: { box: "border-teal-line bg-teal-soft text-[#064e47]", icon: <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-teal" /> },
};

export function Alert({ tone = "info", children, action, className = "" }: { tone?: Tone; children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`flex items-start gap-2.5 rounded-lg border px-3.5 py-3 text-sm ${TONES[tone].box} ${className}`}>
      {TONES[tone].icon}
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <Loader2 aria-hidden className="size-4 animate-spin" />
      {label}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-md bg-[#e9edf0] ${className}`} />;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "teal" }) {
  const styles = tone === "teal" ? "border-teal-line bg-teal-soft text-[#065a52]" : "border-line bg-page text-muted";
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${styles}`}>{children}</span>;
}

export function Disclosure({ label, children, defaultOpen = false, icon }: { label: string; children: ReactNode; defaultOpen?: boolean; icon?: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md py-1 text-sm font-medium text-ink hover:text-teal"
      >
        <ChevronDown aria-hidden className={`size-4 transition-transform ${open ? "rotate-0" : "-rotate-90"}`} />
        {icon}
        {label}
      </button>
      <div id={id} hidden={!open} className="pt-2">
        {open && children}
      </div>
    </div>
  );
}

export function Select({
  label,
  hideLabel = false,
  icon,
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; hideLabel?: boolean; icon?: ReactNode }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className={hideLabel ? "sr-only" : "mb-1 block text-sm font-medium text-ink"}>
        {label}
      </label>
      <div className="relative">
        {icon && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink">{icon}</span>}
        <select
          id={id}
          {...props}
          className={`h-10 w-full min-w-0 appearance-none rounded-lg border border-line-strong bg-surface pr-9 text-sm text-ink hover:border-[#b7c1ca] ${icon ? "pl-9" : "pl-3"}`}
        >
          {children}
        </select>
        <ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink" />
      </div>
    </div>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <h1 id="page-title" tabIndex={-1} className="text-[1.75rem] font-bold leading-tight tracking-[-0.01em] text-navy outline-none sm:text-[2rem]">
        {children}
      </h1>
      {sub && <p className="mt-1.5 text-base text-muted">{sub}</p>}
    </div>
  );
}
