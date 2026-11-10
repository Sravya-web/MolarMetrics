import { Upload } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Card } from "../components/ui";
import { useRouter } from "../lib/router";
import { useSession } from "../state/session";

/** Shown on Overview and Ask before any dataset is active. Sample data is
 *  never loaded automatically: the user chooses it here or on Data & Uploads. */
export function NoDataset() {
  const { navigate } = useRouter();
  const { activateSample } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card className="px-6 py-10 text-center">
      <h2 className="text-lg font-semibold text-navy">No clinic data yet</h2>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-muted">Upload your clinic's CSV files to see your overview, or explore the sample clinic first.</p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <Button onClick={() => navigate("/data")}>
          <Upload aria-hidden className="size-4" />
          Upload data
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await activateSample();
            } catch (err) {
              setError(err instanceof Error ? err.message : "The sample data couldn't be opened.");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Opening…" : "Explore sample data"}
        </Button>
      </div>
      {error && <Alert tone="error" className="mx-auto mt-4 max-w-md text-left">{error}</Alert>}
    </Card>
  );
}
