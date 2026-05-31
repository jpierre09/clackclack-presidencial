export function AlertLegend() {
  return (
    <div className="alert-legend" aria-label="Significado de alertas">
      <span className="legend-item danger">
        <img src="/alert-danger.svg" alt="Alerta roja" className="alert-logo" />
        <strong>Roja:</strong>
        <small>Suma de votos por fórmula supera total de votos en urna.</small>
      </span>
      <span className="legend-item info">
        <span className="alert-dot-info legend-dot" />
        <strong>Azul:</strong>
        <small>Novedad reportada por validador manual.</small>
      </span>
    </div>
  );
}
