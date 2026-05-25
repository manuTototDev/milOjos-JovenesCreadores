"""
rnpdno_test.py
Prueba de descarga de 10 fichas del RNPDNO.
Extrae foto del PDF + guarda JSON con metadata.
"""
import os
import re
import json
import time
import urllib.request
import urllib.error

# ── Configuración ─────────────────────────────────────────────────
OUT_DIR  = os.path.join(os.path.dirname(__file__), '..', 'rnpdno_test')
API_BASE = 'https://apiconsultapublicarnpdno.segob.gob.mx'
HEADERS  = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://consultapublicarnpdno.segob.gob.mx/',
    'Origin':  'https://consultapublicarnpdno.segob.gob.mx',
}

# Endpoints a probar para el listado de personas
LIST_CANDIDATES = [
    '/api/personas?pagina=1&limite=10',
    '/api/personas?page=1&limit=10',
    '/api/consulta?pagina=1&limite=10',
    '/api/registros?pagina=1&limite=10',
    '/api/personas/consulta?pagina=1&limite=10',
    '/api/boletines?pagina=1&limite=10',
    '/api/v1/personas?pagina=1&limite=10',
    '/api/fichas?pagina=1&limite=10',
    '/Dashboard/ObtenerPersonasDesaparecidas?pagina=1&limite=10',
    '/api/Dashboard/ObtenerPersonas?pagina=1&limite=10',
]

def get_json(path):
    url = API_BASE + path
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read()
            print(f'  ✓ {url} → {r.status} ({len(body)} bytes)')
            return json.loads(body)
    except urllib.error.HTTPError as e:
        print(f'  ✗ {url} → HTTP {e.code}')
    except Exception as e:
        print(f'  ✗ {url} → {type(e).__name__}: {e}')
    return None

def try_pdf(token):
    """Intenta descargar el PDF de una persona por su token."""
    pdf_endpoints = [
        f'/api/pdf/{token}',
        f'/api/boletin/{token}',
        f'/api/ficha/{token}',
        f'/api/personas/{token}/pdf',
        f'/api/fichas/{token}.pdf',
    ]
    for path in pdf_endpoints:
        url = API_BASE + path
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                content_type = r.headers.get('Content-Type', '')
                body = r.read()
                if 'pdf' in content_type.lower() or body[:4] == b'%PDF':
                    print(f'    ✓ PDF encontrado: {url} ({len(body):,} bytes)')
                    return url, body
        except:
            pass
    return None, None

def extract_image_from_pdf(pdf_bytes, out_path):
    """Extrae la primera imagen del PDF usando PyMuPDF (fitz) o reporta error."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        for page in doc:
            images = page.get_images(full=True)
            if images:
                xref = images[0][0]
                base_img = doc.extract_image(xref)
                img_bytes = base_img['image']
                ext = base_img['ext']
                img_out = out_path.replace('.jpg', f'.{ext}')
                with open(img_out, 'wb') as f:
                    f.write(img_bytes)
                print(f'    ✓ Imagen extraída: {img_out}')
                return img_out
        # Si no hay imágenes embebidas, renderiza primera página como imagen
        page = doc[0]
        pix = page.get_pixmap(dpi=150)
        pix.save(out_path)
        print(f'    ✓ Página renderizada: {out_path}')
        return out_path
    except ImportError:
        print('    ✗ PyMuPDF no instalado. Instalando...')
        os.system('pip install pymupdf --quiet')
        return None
    except Exception as e:
        print(f'    ✗ Error extrayendo imagen: {e}')
        return None

def extract_text_from_pdf(pdf_bytes):
    """Extrae todo el texto del PDF para construir el JSON de metadata."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        text = ''
        for page in doc:
            text += page.get_text()
        return text.strip()
    except:
        return ''

def parse_metadata(text, token):
    """Parsea el texto del PDF para extraer campos clave."""
    meta = {'token': token, 'texto_completo': text}
    patterns = {
        'folio':         r'(?:Folio|FOLIO)[:\s]+([A-Z0-9/-]+)',
        'nombre':        r'(?:Nombre|NOMBRE)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)',
        'fecha_nac':     r'(?:Fecha de [Nn]acimiento|FECHA DE NACIMIENTO)[:\s]+([\d/\-]+)',
        'fecha_desap':   r'(?:Fecha de [Dd]esaparici[oó]n|FECHA DE DESAPARICI)[:\s]+([\d/\-]+)',
        'edad':          r'(?:Edad|EDAD)[:\s]+(\d+)',
        'sexo':          r'(?:Sexo|SEXO)[:\s]+([A-Za-záéíóú]+)',
        'estado':        r'(?:Estado|ESTADO)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)',
        'municipio':     r'(?:Municipio|MUNICIPIO)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            meta[key] = m.group(1).strip()
    return meta

# ═══════════════════════════════════════════════════════════════════
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f'Directorio de salida: {OUT_DIR}\n')

    # ── PASO 1: Encontrar endpoint de listado ──────────────────────
    print('='*60)
    print('PASO 1: Buscando endpoint de listado...')
    print('='*60)
    data = None
    working_endpoint = None
    for path in LIST_CANDIDATES:
        result = get_json(path)
        if result is not None:
            data = result
            working_endpoint = path
            break
        time.sleep(0.3)

    if data is None:
        print('\n[!] Ningún endpoint estándar funcionó.')
        print('    Intentando el JS bundle para extraer endpoints...')
        # Último recurso: extraer del JS
        js_url = 'https://consultapublicarnpdno.segob.gob.mx/assets/index-DiPcmp98.js'
        req = urllib.request.Request(js_url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                js = r.read().decode('utf-8', errors='ignore')
            paths = re.findall(r'["`\'](/[a-zA-Z0-9/_-]*(?:persona|registro|boletin|ficha|consulta)[a-zA-Z0-9/_-]*)["`\']', js, re.IGNORECASE)
            print(f'  Rutas encontradas en JS: {sorted(set(paths))}')
        except Exception as e:
            print(f'  Error leyendo JS: {e}')
        return

    print(f'\n✓ Endpoint funcionando: {working_endpoint}')
    print(f'Respuesta (primeros 500 chars): {str(data)[:500]}')

    # ── PASO 2: Extraer lista de personas ─────────────────────────
    print('\n' + '='*60)
    print('PASO 2: Extrayendo registros...')
    print('='*60)

    # Detectar la estructura de la respuesta
    records = []
    if isinstance(data, list):
        records = data[:10]
    elif isinstance(data, dict):
        for key in ['data', 'personas', 'registros', 'items', 'results', 'fichas']:
            if key in data:
                records = data[key][:10]
                break
        if not records:
            print(f'Claves disponibles: {list(data.keys())}')
            print(f'Muestra: {str(data)[:400]}')
            return

    print(f'Registros encontrados: {len(records)}\n')

    # ── PASO 3: Procesar cada persona ─────────────────────────────
    print('='*60)
    print('PASO 3: Descargando PDFs y extrayendo fotos...')
    print('='*60)

    results_summary = []
    for i, rec in enumerate(records[:10], 1):
        print(f'\n[{i}/10] {rec}')

        # Detectar el token / ID del registro
        token = None
        for key in ['token', 'id', 'folio', 'uuid', 'idPersona', 'IdPersona', 'folioUnico']:
            if key in rec:
                token = str(rec[key])
                break
        if not token:
            print(f'  [!] No se encontró token en: {list(rec.keys())}')
            continue

        print(f'  Token: {token}')

        # Descargar PDF
        pdf_url, pdf_bytes = try_pdf(token)
        if not pdf_bytes:
            print(f'  [!] No se pudo descargar PDF')
            results_summary.append({'token': token, 'error': 'no_pdf', 'data': rec})
            continue

        # Guardar PDF
        pdf_path = os.path.join(OUT_DIR, f'{i:02d}_{token}.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)

        # Extraer imagen
        img_path = os.path.join(OUT_DIR, f'{i:02d}_{token}_foto.jpg')
        extract_image_from_pdf(pdf_bytes, img_path)

        # Extraer texto y parsear metadata
        text = extract_text_from_pdf(pdf_bytes)
        meta = parse_metadata(text, token)
        meta['api_data'] = rec  # datos originales del API
        meta['pdf_url'] = pdf_url

        # Guardar JSON
        json_path = os.path.join(OUT_DIR, f'{i:02d}_{token}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f'    ✓ JSON guardado: {json_path}')
        results_summary.append(meta)

        time.sleep(0.5)  # rate limit

    # ── RESUMEN ───────────────────────────────────────────────────
    print('\n' + '='*60)
    print('RESUMEN')
    print('='*60)
    print(f'Procesados: {len(results_summary)}/10')
    ok = [r for r in results_summary if 'error' not in r]
    print(f'Con PDF + foto: {len(ok)}')
    summary_path = os.path.join(OUT_DIR, '_resumen.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)
    print(f'Resumen guardado: {summary_path}')

if __name__ == '__main__':
    main()
