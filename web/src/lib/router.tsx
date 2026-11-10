import { createContext, useCallback, useContext, useEffect, useMemo, useState, type AnchorHTMLAttributes, type ReactNode } from "react";

export type Route =
  | { name: "home" }
  | { name: "data" }
  | { name: "review"; batchId: string }
  | { name: "overview" }
  | { name: "ask" }
  | { name: "not-found" };

export function parseRoute(path: string): Route {
  const clean = path.replace(/\/+$/, "") || "/";
  if (clean === "/") return { name: "home" };
  if (clean === "/data") return { name: "data" };
  if (clean === "/overview") return { name: "overview" };
  if (clean === "/ask") return { name: "ask" };
  const review = /^\/data\/review\/([a-f0-9]{8,64})$/.exec(clean);
  if (review) return { name: "review", batchId: review[1] };
  return { name: "not-found" };
}

interface RouterValue {
  route: Route;
  navigate: (to: string, options?: { replace?: boolean }) => void;
}

const RouterContext = createContext<RouterValue | null>(null);

/** Move keyboard and screen-reader focus to the new page's heading. */
function focusPageTitle() {
  requestAnimationFrame(() => document.getElementById("page-title")?.focus({ preventScroll: true }));
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => {
      setPath(window.location.pathname);
      focusPageTitle();
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((to: string, options?: { replace?: boolean }) => {
    if (to === window.location.pathname) return;
    if (options?.replace) window.history.replaceState(null, "", to);
    else window.history.pushState(null, "", to);
    setPath(to);
    window.scrollTo({ top: 0 });
    focusPageTitle();
  }, []);

  const value = useMemo(() => ({ route: parseRoute(path), navigate }), [path, navigate]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function useRouter(): RouterValue {
  const value = useContext(RouterContext);
  if (!value) throw new Error("useRouter outside RouterProvider");
  return value;
}

export function Link({ to, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const { navigate } = useRouter();
  return (
    <a
      {...props}
      href={to}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(to);
      }}
    />
  );
}
