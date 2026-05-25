"""
generar_fichas.py — v2
Estética: fondo blanco, tipografía IBM Plex Mono/Sans,
acento rojo #FF2D2D, verde #00FF88 para datos clave.
Basado en el design system del proyecto Mil Ojos (web/frontend).

Genera:
  - Un PDF individual por persona
  - Un compendio _COMPENDIO_FICHAS.pdf con todas las páginas

Uso:
    python generar_fichas.py
"""
import os, json, glob
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Spacer, Paragraph, Table, TableStyle,
    Image as RLImage, HRFlowable, PageBreak, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Circle
from reportlab.graphics import renderPDF

# ── Paleta (light mode IBM Plex) ──────────────────────────────────
W_BG    = colors.white
W_F0    = colors.HexColor('#F5F5F5')   # fondo campos
W_DARK  = colors.HexColor('#0D0D0D')   # texto principal
W_GRAY1 = colors.HexColor('#666666')   # labels
W_GRAY2 = colors.HexColor('#AAAAAA')   # texto secundario
W_GRAY3 = colors.HexColor('#E0E0E0')   # bordes / divisores
W_RED   = colors.HexColor('#FF2D2D')   # acento principal (Mil Ojos)
W_RED2  = colors.HexColor('#CC0000')   # acento oscuro
W_GREEN = colors.HexColor('#00AA55')   # datos confirmados
W_AMBER = colors.HexColor('#E8A000')   # alerta
W_CHIP  = colors.HexColor('#FFF0F0')   # chip rojo suave

W, H = A4

LOGO_NAME = 'MIL OJOS'
MONO = 'Courier'       # IBM Plex Mono → Courier (ReportLab builtin más cercano)
SANS = 'Helvetica'

def st(name, **kw):
    defaults = dict(fontName=SANS, fontSize=10, textColor=W_DARK,
                    leading=14, spaceBefore=0, spaceAfter=0)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)

# ── Estilos ───────────────────────────────────────────────────────
S_LOGO    = st('logo',     fontName=MONO, fontSize=14, textColor=W_DARK,
               letterSpacing=6, leading=20)
S_NAME    = st('name',     fontName=SANS+'-Bold', fontSize=20,
               textColor=W_DARK, leading=26)
S_LABEL   = st('label',    fontName=MONO, fontSize=7, textColor=W_GRAY1,
               letterSpacing=2, leading=10)
S_VALUE   = st('value',    fontName=SANS+'-Bold', fontSize=11,
               textColor=W_DARK, leading=14)
S_VALUE_M = st('valuem',   fontName=SANS, fontSize=10,
               textColor=W_DARK, leading=13)
S_SECTION = st('section',  fontName=MONO, fontSize=8, textColor=W_RED,
               letterSpacing=3, leading=12)
S_FOOTER  = st('footer',   fontName=MONO, fontSize=6, textColor=W_GRAY2,
               alignment=TA_CENTER, letterSpacing=1, leading=9)
S_URL     = st('url',      fontName=MONO, fontSize=6.5, textColor=W_GRAY1,
               alignment=TA_CENTER, letterSpacing=0.5, leading=10)
S_ALERT   = st('alert',    fontName=SANS+'-Bold', fontSize=8,
               textColor=W_BG, leading=11)
S_NOPHOTO = st('nophoto',  fontName=MONO, fontSize=8, textColor=W_GRAY2,
               alignment=TA_CENTER, letterSpacing=1, leading=12)
S_CHIP    = st('chip',     fontName=MONO, fontSize=8, textColor=W_RED,
               letterSpacing=1, leading=11)

def hr(color=W_GRAY3, thickness=0.5, before=3, after=3):
    return HRFlowable(width='100%', thickness=thickness, color=color,
                      spaceBefore=before, spaceAfter=after)

def sp(h=0.25):
    return Spacer(1, h * cm)

def placeholder_foto(w_pt, h_pt):
    """Rectángulo placeholder con X y texto."""
    d = Drawing(w_pt, h_pt)
    d.add(Rect(0, 0, w_pt, h_pt, fillColor=W_F0, strokeColor=W_GRAY3, strokeWidth=1))
    # X diagonal
    d.add(Line(16, 16, w_pt-16, h_pt-16, strokeColor=W_GRAY3, strokeWidth=1.5))
    d.add(Line(w_pt-16, 16, 16, h_pt-16, strokeColor=W_GRAY3, strokeWidth=1.5))
    # Círculo central
    cx, cy = w_pt/2, h_pt/2
    d.add(Circle(cx, cy, 28, fillColor=W_F0, strokeColor=W_GRAY3, strokeWidth=1))
    d.add(String(cx, cy+8, 'SIN FOTO', textAnchor='middle',
                 fontName=MONO, fontSize=7, fillColor=W_GRAY2))
    d.add(String(cx, cy-6, 'DISPONIBLE', textAnchor='middle',
                 fontName=MONO, fontSize=6, fillColor=W_GRAY3))
    return d

def campo_row(labels_vals: list, col_widths: list):
    """Crea una fila de pares label/valor con el estilo IBM Plex."""
    cells = []
    for label, val in labels_vals:
        cell = [
            Paragraph(label.upper(), S_LABEL),
            Paragraph(str(val) if val else '—', S_VALUE),
        ]
        cells.append(cell)

    # Aplanar: cada celda es una lista de párrafos
    flat_cells = []
    for cell in cells:
        flat_cells.append(cell)

    t = Table([flat_cells], colWidths=col_widths)
    t.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING',   (0,0), (-1,-1), 3),
        ('BOTTOMPADDING',(0,0), (-1,-1), 6),
    ]))
    return t

def build_ficha_story(persona: dict, page_idx: int = 0) -> list:
    """Construye la lista de Flowables para una ficha de persona."""
    nombre      = (persona.get('nombre') or 'DESCONOCIDO').upper()
    edad        = persona.get('edad_actual') or '—'
    sexo        = (persona.get('sexo') or persona.get('sexo_api') or '—').upper()
    estado      = (persona.get('estado') or '—').upper()
    municipio   = (persona.get('municipio') or '—').upper()
    fecha_h     = persona.get('fecha_hechos') or '—'
    fecha_p     = persona.get('fecha_percato') or '—'
    estatura    = persona.get('estatura') or '—'
    complexion  = (persona.get('complexion') or '—').upper()
    piel        = (persona.get('color_piel') or '—').upper()
    cabello     = (persona.get('cabello') or '—').upper()
    senas       = persona.get('senas') or '—'
    dependencia = persona.get('dependencia') or f"Dependencia {persona.get('iddependencia','N/D')}"
    folio       = persona.get('folio') or persona.get('idvictima') or '—'
    url_portal  = persona.get('url_portal') or 'https://consultapublicarnpdno.segob.gob.mx/consulta'
    foto_path   = persona.get('foto_path') or ''
    tiene_foto  = bool(foto_path and os.path.exists(foto_path))
    ahora       = datetime.now().strftime('%d/%m/%Y  %H:%M')

    foto_w = 6.2 * cm
    foto_h = 8.0 * cm
    body_w = W - 3*cm - foto_w - 0.6*cm   # ancho panel derecho

    s = []  # story

    # ══════════════════════════════════════════════════════════════
    # HEADER: logo | subtítulo
    # ══════════════════════════════════════════════════════════════
    hdr = Table([[
        Paragraph(LOGO_NAME, S_LOGO),
        Paragraph(
            'COMISIÓN NACIONAL DE BÚSQUEDA<br/>'
            'REGISTRO NACIONAL DE PERSONAS DESAPARECIDAS',
            st(f'hs{page_idx}', fontName=MONO, fontSize=6,
               textColor=W_GRAY1, alignment=TA_RIGHT,
               letterSpacing=1, leading=10)
        ),
    ]], colWidths=[9*cm, 9*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING',(0,0), (-1,-1), 0),
        ('TOPPADDING',  (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
    ]))
    s.append(hdr)
    s.append(HRFlowable(width='100%', thickness=1.5, color=W_RED,
                        spaceBefore=0, spaceAfter=6))

    # ── Banda alerta ──────────────────────────────────────────────
    alert_tbl = Table([[
        Paragraph('PERSONA DESAPARECIDA  ·  SE SOLICITA INFORMACIÓN', S_ALERT)
    ]], colWidths=[18*cm])
    alert_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (-1,-1), W_RED),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('LEFTPADDING',  (0,0), (-1,-1), 10),
    ]))
    s.append(alert_tbl)
    s.append(sp(0.35))

    # ══════════════════════════════════════════════════════════════
    # COLUMNA FOTO + DATOS
    # ══════════════════════════════════════════════════════════════
    if tiene_foto:
        foto_el = RLImage(foto_path, width=foto_w, height=foto_h, kind='proportional')
    else:
        foto_el = placeholder_foto(foto_w, foto_h)

    # Panel derecho de datos
    panel = []
    panel.append(Paragraph(nombre, S_NAME))
    panel.append(sp(0.15))
    panel.append(HRFlowable(width='100%', thickness=0.8, color=W_RED,
                             spaceBefore=0, spaceAfter=5))

    # Grid datos clave
    cw = [2.3*cm, 3.5*cm, 2.5*cm, 3.0*cm]  # 4 columnas
    panel.append(campo_row([('SEXO', sexo), ('EDAD ACTUAL', edad)],
                            [2.3*cm, 3.5*cm, 2.5*cm, 3.0*cm][:2] +
                            [2.5*cm, 3.0*cm]))
    panel.append(campo_row([('ESTADO', estado), ('MUNICIPIO', municipio)],
                            [2.3*cm, 3.5*cm, 2.5*cm, 3.0*cm][:2] +
                            [2.5*cm, 3.0*cm]))
    panel.append(campo_row([('FECHA HECHOS', fecha_h), ('FECHA PERCATO', fecha_p)],
                            [2.3*cm, 3.5*cm, 2.5*cm, 3.0*cm][:2] +
                            [2.5*cm, 3.0*cm]))

    panel.append(HRFlowable(width='100%', thickness=0.5, color=W_GRAY3,
                             spaceBefore=3, spaceAfter=5))
    panel.append(Paragraph('RASGOS FÍSICOS', S_SECTION))
    panel.append(sp(0.1))
    panel.append(campo_row([('ESTATURA', estatura), ('COMPLEXIÓN', complexion)],
                            [2.3*cm, 3.5*cm, 2.5*cm, 3*cm][:2] + [2.5*cm, 3*cm]))
    panel.append(campo_row([('COLOR PIEL', piel), ('CABELLO', cabello)],
                            [2.3*cm, 3.5*cm, 2.5*cm, 3*cm][:2] + [2.5*cm, 3*cm]))

    main_tbl = Table([[foto_el, panel]],
                     colWidths=[foto_w + 0.6*cm, body_w])
    main_tbl.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 0),
    ]))
    s.append(main_tbl)
    s.append(sp(0.3))

    # ══════════════════════════════════════════════════════════════
    # SEÑAS PARTICULARES
    # ══════════════════════════════════════════════════════════════
    s.append(HRFlowable(width='100%', thickness=0.5, color=W_GRAY3,
                         spaceBefore=0, spaceAfter=5))
    s.append(Paragraph('SEÑAS PARTICULARES', S_SECTION))
    s.append(sp(0.1))
    s.append(Paragraph(senas, S_VALUE_M))
    s.append(sp(0.25))

    # ══════════════════════════════════════════════════════════════
    # DATOS DE REGISTRO
    # ══════════════════════════════════════════════════════════════
    s.append(HRFlowable(width='100%', thickness=0.5, color=W_GRAY3,
                         spaceBefore=0, spaceAfter=5))
    s.append(Paragraph('DATOS DE REGISTRO', S_SECTION))
    s.append(sp(0.1))

    reg_style = st(f'rv{page_idx}', fontName=MONO, fontSize=7, textColor=W_GRAY1, leading=10)
    reg_rows = [
        [Paragraph('FOLIO / UUID', S_LABEL),   Paragraph(folio, reg_style),
         Paragraph('DEPENDENCIA', S_LABEL),     Paragraph(dependencia, reg_style)],
        [Paragraph('FUENTE', S_LABEL),          Paragraph('RNPDNO / Comisión Nacional de Búsqueda', reg_style),
         Paragraph('GENERADO', S_LABEL),        Paragraph(ahora, reg_style)],
    ]
    for row in reg_rows:
        flat = [row]
        t = Table(flat, colWidths=[2.3*cm, 8*cm, 2.3*cm, 5.9*cm])
        t.setStyle(TableStyle([
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING',  (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING',   (0,0), (-1,-1), 2),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ]))
        s.append(t)

    s.append(sp(0.3))

    # ══════════════════════════════════════════════════════════════
    # CTA VERDE — cotejar en portal oficial
    # ══════════════════════════════════════════════════════════════
    cta_tbl = Table([[
        Paragraph(
            'Si tienes información sobre esta persona, '
            'contáctanos al <b>800 008 3500</b>  ·  '
            '<b>Comisión Nacional de Búsqueda de Personas</b>',
            st(f'cta{page_idx}', fontName=SANS, fontSize=8,
               textColor=W_BG, alignment=TA_CENTER, leading=13)
        )
    ]], colWidths=[18*cm])
    cta_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (-1,-1), W_GREEN),
        ('TOPPADDING',   (0,0), (-1,-1), 7),
        ('BOTTOMPADDING',(0,0), (-1,-1), 7),
        ('LEFTPADDING',  (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    s.append(cta_tbl)
    s.append(sp(0.2))

    # ── URL portal para cotejar ───────────────────────────────────
    s.append(Paragraph(
        f'Coteja en el portal oficial: <u>{url_portal}</u>',
        S_URL
    ))
    s.append(sp(0.15))

    # ── Footer ───────────────────────────────────────────────────
    s.append(HRFlowable(width='100%', thickness=0.5, color=W_GRAY3,
                         spaceBefore=0, spaceAfter=3))
    s.append(Paragraph(
        f'MIL OJOS  ·  Sistema de Búsqueda Facial  '
        f'·  RNPDNO / CNB  ·  Generado {ahora}',
        S_FOOTER
    ))

    return s

# ── Callback de fondo blanco ──────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(W_BG)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    canvas.restoreState()

# ── Generar PDF individual ────────────────────────────────────────
def generar_ficha_pdf(persona: dict, out_path: str, idx: int = 0):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.4*cm,  bottomMargin=1.2*cm,
    )
    doc.build(build_ficha_story(persona, idx),
              onFirstPage=on_page, onLaterPages=on_page)

# ── Main ─────────────────────────────────────────────────────────
def main():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, '..', 'rnpdno_data')

    resumen_path = os.path.join(DATA_DIR, '_resumen.json')
    if not os.path.exists(resumen_path):
        print(f'ERROR: no se encontró {resumen_path}')
        return

    with open(resumen_path, encoding='utf-8') as f:
        personas = json.load(f)

    print(f'Generando fichas para {len(personas)} personas...\n')
    pdfs = []

    for i, persona in enumerate(personas, 1):
        nombre_safe = (persona.get('nombre') or f'persona_{i}').upper()
        nombre_safe = ''.join(c if c.isalnum() or c == '_' else '_' for c in nombre_safe)[:28]
        out = os.path.join(DATA_DIR, f'{i:02d}_{nombre_safe}_ficha.pdf')
        try:
            generar_ficha_pdf(persona, out, i)
            size = os.path.getsize(out) // 1024
            print(f'  [{i:02d}] {persona.get("nombre","?")} → {os.path.basename(out)} ({size}KB)')
            pdfs.append(out)
        except Exception as e:
            print(f'  [ERR {i}] {e}')
            import traceback; traceback.print_exc()

    # ── Compendio ─────────────────────────────────────────────────
    print(f'\nGenerando compendio...')
    compendio = os.path.join(DATA_DIR, '_COMPENDIO_FICHAS.pdf')
    doc = SimpleDocTemplate(
        compendio, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.4*cm,  bottomMargin=1.2*cm,
    )
    combined = []
    for i, persona in enumerate(personas):
        if i > 0:
            combined.append(PageBreak())
        combined.extend(build_ficha_story(persona, i))

    doc.build(combined, onFirstPage=on_page, onLaterPages=on_page)
    size = os.path.getsize(compendio) // 1024
    print(f'  Compendio: {os.path.basename(compendio)} ({size}KB, {len(personas)} páginas)')

    print(f'\n{"="*60}')
    print(f'PDFs: {len(pdfs)} individuales + 1 compendio')
    print(f'Carpeta: {os.path.abspath(DATA_DIR)}')

if __name__ == '__main__':
    main()
