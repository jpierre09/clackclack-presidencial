export function AlertLegend() {
  return (
    <div className="alert-legend" aria-label="Significado de alertas">
      <span className="legend-item danger">
        <img src="/alert-danger.svg" alt="Alerta roja" className="alert-logo" />
        <strong>Roja:</strong>
        <small>Diferencia PH Senado vs Camara igual o mayor al 10%.</small>
      </span>
      <span className="legend-item warning">
        <img src="/alert-warning.svg" alt="Alerta amarilla" className="alert-logo" />
        <strong>Amarilla:</strong>
        <small>Baja confianza OCR, requiere validacion manual.</small>
      </span>
    </div>
  );
}
