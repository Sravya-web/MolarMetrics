import { Database, House, Menu, MessageSquare, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useRouter } from "../lib/router";
import { ToothMark } from "./ToothMark";

const NAV = [
  { to: "/overview", label: "Overview", icon: House, match: ["overview"] },
  { to: "/ask", label: "Ask MolarMetrics", icon: MessageSquare, match: ["ask"] },
  { to: "/data", label: "Data & Uploads", icon: Database, match: ["data", "review"] },
] as const;

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { route } = useRouter();
  return (
    <ul className="space-y-1">
      {NAV.map(({ to, label, icon: Icon, match }) => {
        const current = (match as readonly string[]).includes(route.name);
        return (
          <li key={to}>
            <Link
              to={to}
              onClick={onNavigate}
              aria-current={current ? "page" : undefined}
              className={`flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-[13.5px] ${
                current ? "bg-teal-soft font-semibold text-[#06564f]" : "text-ink hover:bg-[#eef2f3]"
              }`}
            >
              <Icon aria-hidden className="size-[18px] shrink-0" strokeWidth={1.8} />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Wordmark() {
  return (
    <Link to="/overview" className="flex items-center gap-2 rounded-md text-navy">
      <ToothMark className="size-6" />
      <span className="text-[1.05rem] font-bold tracking-[-0.01em]">MolarMetrics</span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="min-h-dvh bg-surface lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:font-semibold">
        Skip to content
      </a>

      {/* Desktop: narrow sidebar */}
      <aside className="hidden w-[200px] shrink-0 border-r border-line bg-rail lg:block">
        <div className="sticky top-0 flex h-dvh flex-col px-3 py-6">
          <div className="px-2 pb-7">
            <Wordmark />
          </div>
          <nav aria-label="Main">
            <NavItems />
          </nav>
        </div>
      </aside>

      {/* Mobile: top bar with a menu */}
      <header className="sticky top-0 z-30 border-b border-line bg-surface lg:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <Wordmark />
          <button
            ref={menuButton}
            type="button"
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMenuOpen((v) => !v)}
            className="inline-flex size-10 items-center justify-center rounded-lg text-navy hover:bg-page"
          >
            {menuOpen ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
            <span className="sr-only">{menuOpen ? "Close menu" : "Open menu"}</span>
          </button>
        </div>
        <nav id="mobile-nav" aria-label="Main" hidden={!menuOpen} className="border-t border-line px-3 pb-3 pt-2">
          <NavItems onNavigate={() => setMenuOpen(false)} />
        </nav>
      </header>

      <main id="main" className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-[1120px] px-4 py-6 sm:px-8 sm:py-8 lg:px-10 lg:py-9">{children}</div>
      </main>
    </div>
  );
}
