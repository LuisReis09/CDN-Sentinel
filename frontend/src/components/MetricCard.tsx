import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  caption: string;
  icon: LucideIcon;
  tone?: "cyan" | "orange" | "green" | "red";
}

export function MetricCard({ label, value, caption, icon: Icon, tone = "cyan" }: MetricCardProps) {
  return (
    <article className={`metric-card tone-${tone}`}>
      <div className="metric-card__icon"><Icon size={17} /></div>
      <div>
        <p className="eyebrow">{label}</p>
        <strong>{value}</strong>
        <span>{caption}</span>
      </div>
    </article>
  );
}

