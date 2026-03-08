interface AlertBadgeProps {
  danger: number;
  warning?: number;
  compact?: boolean;
}

export function AlertBadge({ danger, warning = 0, compact = false }: AlertBadgeProps) {
  const total = danger + warning;
  if (total === 0) {
    return <span className="alert-badge empty">Sin alertas</span>;
  }

  return (
    <span className="alert-badge">
      {danger > 0 ? (
        <span className="alert-token danger">
          <img src="/alert-danger.svg" alt="Alerta roja" className="alert-logo" />
          <strong className="alert-count">{danger}</strong>
          {!compact ? <small className="alert-label">rojas</small> : null}
        </span>
      ) : null}
      {warning > 0 ? (
        <span className="alert-token warning">
          <img src="/alert-warning.svg" alt="Alerta amarilla" className="alert-logo" />
          <strong className="alert-count">{warning}</strong>
          {!compact ? <small className="alert-label">amarillas</small> : null}
        </span>
      ) : null}
    </span>
  );
}
