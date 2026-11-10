import { Database } from "lucide-react";
import { useState } from "react";
import { useSession } from "../state/session";
import { Badge, Select } from "./ui";

/** The active-dataset selector. Switching resets every dataset-specific view. */
export function DatasetSelect() {
  const { state, active, activate } = useSession();
  const [error, setError] = useState<string | null>(null);
  if (!state || !active) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        label="Dataset"
        hideLabel
        icon={<Database aria-hidden className="size-4" strokeWidth={1.8} />}
        value={active.id}
        onChange={async (event) => {
          setError(null);
          try {
            await activate(event.target.value);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Couldn't switch datasets.");
          }
        }}
        className="w-[230px] max-w-full"
      >
        {state.datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </Select>
      {active.kind === "sample" && <Badge>Sample data</Badge>}
      {error && <span role="alert" className="text-sm text-danger">{error}</span>}
    </div>
  );
}
