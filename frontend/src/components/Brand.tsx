import Link from "next/link";

export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span className={`brand-mark ${className}`} aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none">
        <rect
          x="5"
          y="4"
          width="22"
          height="24"
          rx="5"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <path
          d="M5 11h22M5 21h22M12 4v4m8-4v4M12 24v4m8-4v4M12 16h8m-4-3v6"
          stroke="currentColor"
          strokeWidth="1.6"
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
