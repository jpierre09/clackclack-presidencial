interface MetricCardProps {
  label: string;
  value: number | string;
  tone?: "neutral" | "danger" | "warning" | "success";
}

export function MetricCard({ label, value, tone = "neutral" }: MetricCardProps) {
  return (
    <div className={`metric-card tone-${tone}`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  );
}
