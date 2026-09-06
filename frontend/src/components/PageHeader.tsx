import type { ReactNode } from "react";

export default function PageHeader({
  title,
  description,
  eyebrow = "Your weekly edge",
  actions,
}: {
  title: ReactNode;
  description: ReactNode;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div className="min-w-0">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
