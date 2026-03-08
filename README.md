# ClackClack - Auditor Electoral E-14 Antioquia 2026

Sistema de auditoria electoral para las elecciones legislativas de Colombia 2026, enfocado en Antioquia. Descarga, lee y valida los formularios E-14 (actas de escrutinio) para detectar discrepancias en los votos del Pacto Historico entre Senado y Camara.

## Arquitectura

### Backend (Python/FastAPI)
- **FastAPI** con SQLite (aiosqlite) como base de datos
- **OCR dual**: Tesseract/OpenCV (legacy) y **Claude Vision API** (nuevo, preferido)
- **Event Bus** con SSE para actualizaciones en tiempo real
- **Alert Engine** detecta discrepancias de votos (>10%) y baja confianza OCR (<60%)
- **DOCX Generator** para documentos de reclamacion formal
- **Local Ingest** escanea carpeta `e14_downloads/` para procesar PDFs automaticamente
- **Remote Poller** (opcional) descarga PDFs de la Registraduria

### Frontend (React/TypeScript/Vite)
- Dashboard con metricas en tiempo real
- Pagina de validacion mesa por mesa
- Pagina de resultados con tabla jerarquica
- Mapa (preparado pero sin datos geo aun)
- Pagina de configuracion

## Estructura de Archivos Clave

```
ClackClack/
  backend/
    main.py              # FastAPI entrypoint, lifespan, routers
    config.py            # Configuracion central (rutas, thresholds, flags)
    database.py          # SQLite async (aiosqlite)
    models.py            # Pydantic models (Puesto, E14Result, Alert, etc.)
    ocr/
      ocr_engine.py      # Motor Tesseract (legacy)
      ocr_config.py      # Config Tesseract
      image_processing.py # Preprocesamiento OpenCV
      e14_parser_v2.py   # Parser completo Tesseract
    services/
      claude_ocr.py      # ** Motor Claude Vision API (reemplaza Tesseract) **
      ocr_processor.py   # Wrapper async que llama a e14_parser_v2
      alert_engine.py    # Evalua discrepancias SEN vs CAM
      local_ingest.py    # Escanea carpeta local de PDFs
      downloader.py      # Descarga PDFs de Registraduria
      docx_generator.py  # Genera documentos de reclamacion
      event_bus.py       # Pub/sub para SSE
      comisiones_loader.py # Carga datos de comisiones
      divipole_loader.py # Carga division politica
    routers/
      dashboard.py, alerts.py, validation.py, reclamation.py,
      settings.py, system.py, sse.py
    tools/
      eval_ocr.py        # Evaluacion de precision OCR
      bench_parallel.py  # Benchmark de procesamiento paralelo
  frontend/src/
    App.tsx, main.tsx, api.ts, types.ts, style.css
    components/ (FilterBar, MetricCard, StatusPill, AlertBadge, TopBar, AlertLegend)
    pages/      (Dashboard, Validation, Results, Map, Settings)
  data/
    antioquia_puestos.json       # Puestos de votacion
    distribucion_comisiones.xlsx # Comisiones escrutadoras
    demo-pdfs/                   # PDFs de prueba
  e14_downloads/                 # PDFs descargados (estructura jerarquica)
  test_claude_ocr.py             # Script de prueba para Claude Vision
```

## Requisitos

- Python 3.11+
- Node 18+
- Tesseract OCR instalado y en PATH (solo si se usa motor legacy)

## Ejecucion rapida

```bash
# Backend
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (otra terminal)
cd frontend && npm install && npm run dev

# O todo junto:
python run.py
```

## Variables de Entorno

| Variable | Default | Descripcion |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | API key de Claude para OCR con Vision |
| `CLACK_DEMO_EXPO_MODE` | false | Modo demo (genera datos falsos, sirve frontend) |
| `CLACK_ENABLE_LOCAL_INGEST` | true | Escaneo automatico de carpeta e14_downloads |
| `CLACK_ENABLE_REMOTE_POLLER` | false | Descarga de PDFs desde Registraduria |
| `CLACK_SERVE_FRONTEND` | false | Sirve frontend desde FastAPI |

## Costos Estimados Claude Vision

- Modelo: claude-haiku-4-5 ($0.80/M input, $4.00/M output)
- ~100 DPI por pagina para minimizar tokens
- Presupuesto: $100 USD para ~30,000 E-14 de Antioquia

## Progreso del Proyecto

### Completado
1. Estructura base backend FastAPI con SQLite
2. Frontend React con dashboard, validacion, resultados
3. Motor OCR Tesseract/OpenCV (e14_parser_v2) - funcional pero baja precision en digitos manuscritos
4. Sistema de alertas (discrepancia votos SEN vs CAM, baja confianza)
5. Event bus con SSE para tiempo real
6. Generador de documentos DOCX para reclamaciones
7. Local ingest (escaneo automatico de carpeta e14_downloads)
8. Demo mode con datos de prueba
9. **Servicio Claude Vision OCR** (`claude_ocr.py`) - implementado con:
   - Renderizado PDF a imagenes PNG (100 DPI para minimizar tokens)
   - Prompt optimizado para extraer todos los campos del E-14
   - Calculo de costos y proyeccion para 30K documentos
   - Conversion de resultado Claude al formato DB existente
   - Wrapper async para integracion con FastAPI
10. **Script de prueba** (`test_claude_ocr.py`) con validacion automatica

### En Progreso (sesion actual)
11. **Prueba real con API key de Claude** - Ejecutar test contra PDF real para validar extraccion

### Pendiente
12. Integrar claude_ocr como motor principal reemplazando Tesseract en ocr_processor.py
13. Procesamiento batch con control de rate limiting y costos
14. Cache de resultados para no reprocesar PDFs ya leidos
15. Mapa con datos georreferenciados
16. Pruebas de precision comparando Tesseract vs Claude en batch

## Notas
- El poller remoto esta desactivado por defecto porque el endpoint puede bloquear trafico automatico fuera de jornada.
- Los E14 de prueba estan en `e14_downloads/01-ANTIOQUIA/...` y `data/demo-pdfs/`.
