interface StatusPillProps {
  status: string | null;
}

export function StatusPill({ status }: StatusPillProps) {
  const normalized = (status || "pendiente").toLowerCase();
  const tone = normalized === "processed" || normalized === "corrected"
    ? "success"
    : normalized === "error"
    ? "danger"
    : "neutral";

  return <span className={`status-pill ${tone}`}>{normalized}</span>;
}
