import Link from "next/link";
import { ArrowRight, CircleAlert, ClipboardList, Loader2 } from "lucide-react";

export function EmptyState({
  title,
  description,
  href,
  action,
}: {
  title: string;
  description: string;
  href?: string;
  action?: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">
        <ClipboardList className="h-6 w-6" aria-hidden="true" />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {href && action && (
        <Link className="button-secondary mt-5" href={href}>
          {action}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}
export function LoadingState({
  label = "Loading your league…",
}: {
  label?: string;
}) {
  return (
    <div className="mt-6 space-y-4" role="status" aria-label={label}>
      <p className="flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {label}
      </p>
      <div className="grid gap-4 sm:grid-cols-3" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="rounded-2xl border border-gray-200 bg-white p-6"
          >
            <div className="skeleton h-3 w-20" />
            <div className="skeleton mt-4 h-8 w-28" />
          </div>
        ))}
      </div>
    </div>
  );
}
export function ErrorState({
  message = "We couldn’t load this view. Please try again.",
  retry,
}: {
  message?: string;
  retry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <CircleAlert className="h-5 w-5 shrink-0" aria-hidden="true" />
      <p className="flex-1">{message}</p>
      {retry && (
        <button
          className="font-semibold underline underline-offset-4"
          onClick={retry}
        >
          Try again
        </button>
      )}
    </div>
  );
}
