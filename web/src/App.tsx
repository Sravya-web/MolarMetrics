import { useEffect } from "react";
import { AppShell } from "./components/AppShell";
import { Alert, Button, PageTitle, Spinner } from "./components/ui";
import { Link, RouterProvider, useRouter } from "./lib/router";
import { AskPage } from "./pages/AskPage";
import { DataPage } from "./pages/DataPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SessionProvider, useSession } from "./state/session";

function Screens() {
  const { route, navigate } = useRouter();
  const { state, loading, error, active, refresh } = useSession();

  useEffect(() => {
    if (route.name === "home" && state) navigate(active ? "/overview" : "/data", { replace: true });
  }, [route.name, state, active, navigate]);

  if (loading) return <Spinner label="Loading…" />;
  if (!state) {
    return (
      <Alert tone="error" action={<Button variant="secondary" size="sm" onClick={() => void refresh()}>Try again</Button>}>
        {error ?? "MolarMetrics isn't responding. Check that it is running, then try again."}
      </Alert>
    );
  }
  switch (route.name) {
    case "data":
      return <DataPage />;
    case "review":
      return <ReviewPage key={route.batchId} batchId={route.batchId} />;
    case "overview":
      return <OverviewPage />;
    case "ask":
      return <AskPage />;
    case "home":
      return <Spinner label="Loading…" />;
    default:
      return (
        <div className="space-y-4">
          <PageTitle>Page not found.</PageTitle>
          <Link to="/overview" className="font-medium text-teal underline">
            Go to the overview
          </Link>
        </div>
      );
  }
}

export function App() {
  return (
    <RouterProvider>
      <SessionProvider>
        <AppShell>
          <Screens />
        </AppShell>
      </SessionProvider>
    </RouterProvider>
  );
}
