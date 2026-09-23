import Link from "next/link";

export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span className={`brand-mark ${className}`} aria-hidden="true">
      {/* Broadcast field lines: first-down yellow over scrimmage blue. */}
      <svg viewBox="0 0 32 32" fill="none">
        <path
          d="M9 6v3m0 5v4m0 5v3M23 6v3m0 5v4m0 5v3"
          stroke="currentColor"
          strokeOpacity=".35"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <path
          d="M4 11.5h24"
          stroke="rgb(var(--signal))"
          strokeWidth="2.6"
          strokeLinecap="round"
        />
        <path
          d="M4 20.5h24"
          stroke="#6b8aff"
          strokeWidth="2.6"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export default function Brand({
  href = "/dashboard",
  light = false,
}: {
  href?: string;
  light?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`brand ${light ? "brand-light" : ""}`}
      aria-label="FFAI home"
    >
      <BrandMark />
      <span>
        FFAI<span className="brand-caption">Fantasy football, informed.</span>
      </span>
    </Link>
  );
}
