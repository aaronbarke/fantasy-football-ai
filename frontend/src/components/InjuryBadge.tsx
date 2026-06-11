import { injuryColor } from "@/lib/utils";

export default function InjuryBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${injuryColor(status)}`}
    >
      {status}
    </span>
  );
}
