"""
descargar_fichas_oficiales.py  v2
Para cada persona publica en RNPDNO:
  1. Carga el portal, hace Buscar
  2. Abre el modal de la card via click en primer link
  3. Selecciona radio de dependencia
  4. Hace screenshot del modal-content y lo guarda como PDF (via Pillow)
  5. Guarda imagen de foto (de API) y JSON de datos

Archivos: NOMBRE_APELLIDO_ficha_oficial.pdf / _foto.png / _datos.json

Uso:
    python descargar_fichas_oficiales.py
"""
import os, json, base64, re, io
from playwright.sync_api import sync_playwright
from PIL import Image

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(BASE_DIR, '..', 'rnpdno_data')
PORTAL_URL = 'https://consultapublicarnpdno.segob.gob.mx/consulta'
MAX_ITEMS  = 10
os.makedirs(OUT_DIR, exist_ok=True)

def safe_name(nombre: str, sufijo: str, ext: str) -> str:
    safe = re.sub(r'[^A-Za-z0-9]', '_', nombre.upper()).strip('_')[:50]
    return os.path.join(OUT_DIR, f'{safe}_{sufijo}.{ext}')

def main():
    print(f'Salida  = {os.path.abspath(OUT_DIR)}')
    print(f'Limite  = {MAX_ITEMS}\n')

    imgs_by_id: dict[str, str]  = {}
    imgs_meta:  dict[str, dict] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=['--start-maximized'],
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1440, 'height': 900},
        )
        page = ctx.new_page()

        # Interceptar imagenes API
        def on_resp(resp):
            if 'apiconsulta' not in resp.url:
                return
            try:
                ct = resp.headers.get('content-type', '')
                if 'json' not in ct and 'text' not in ct:
                    return
                body   = json.loads(resp.body())
                result = body.get('result', {})
                if not result.get('success'):
                    return
                inner = result.get('data', '')
                post  = json.loads(resp.request.post_data or '{}')
                ds    = post.get('dataSend', {})
                vid   = ds.get('idvictimadirecta', '')
                if isinstance(inner, str) and inner.startswith('data:image') and vid:
                    if vid not in imgs_by_id:
                        imgs_by_id[vid] = inner
                        imgs_meta[vid]  = {
                            'idreporte':     ds.get('idreporte', ''),
                            'iddependencia': ds.get('iddependenciaorigen', ''),
                            'sexo_api':      ds.get('sexo', ''),
                        }
            except Exception:
                pass

        page.on('response', on_resp)

        # Cargar portal
        print('Cargando portal...')
        page.goto(PORTAL_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(4000)

        # Click en Buscar
        for buscar_txt in ['Buscar', 'BUSCAR', 'Consultar']:
            try:
                page.get_by_text(buscar_txt, exact=False).first.click(timeout=3000)
                page.wait_for_timeout(5000)
                if page.locator('.ctn-card-consulta').count() > 0:
                    break
            except:
                pass

        cnt = page.locator('.ctn-card-consulta').count()
        print(f'Cards en portal: {cnt}')
        if cnt == 0:
            print('ERROR: No se encontraron cards. Abortando.')
            browser.close()
            return

        # Leer datos DOM de las cards
        cards_dom = page.evaluate(r'''() => {
            return [...document.querySelectorAll("div.card.ctn-card-consulta")].map(card => {
                const titulo   = card.querySelector(".texto-card-consulta")?.innerText.trim() || "";
                const completo = card.querySelector(".texto-complemetario-card")?.innerText.trim() || "";
                const esConf   = titulo.toUpperCase().includes("CONFIDENCIAL") || titulo === "";
                const campos   = {};
                completo.split("\n").forEach(line => {
                    const m = line.match(/^([^:]+):\s*(.+)$/);
                    if (m) campos[m[1].trim()] = m[2].trim();
                });
                return { nombre: titulo, confidencial: esConf, campos };
            });
        }''')

        publicas = [c for c in cards_dom if not c['confidencial'] and c['nombre']]
        print(f'Cards publicas: {len(publicas)}')

        # Indices de cards publicas en el DOM
        all_map = page.evaluate(r'''() =>
            [...document.querySelectorAll("div.card.ctn-card-consulta")].map(
                (c,i) => ({ idx: i, conf: c.innerText.toUpperCase().includes("CONFIDENCIAL") })
            )
        ''')
        pub_indices = [x['idx'] for x in all_map if not x['conf']]

        resumen = []
        for iter_i, (dom_idx, card_data) in enumerate(zip(pub_indices[:MAX_ITEMS], publicas[:MAX_ITEMS])):
            nombre = card_data['nombre']
            campos = card_data['campos']
            n      = iter_i + 1
            print(f'\n[{n:02d}/{min(len(publicas), MAX_ITEMS)}] {nombre}')

            # Click en primer link de la card
            card_el = page.locator('div.card.ctn-card-consulta').nth(dom_idx)
            try:
                card_el.scroll_into_view_if_needed()
                page.wait_for_timeout(600)
                link = card_el.locator('a').first
                link.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                link.click(timeout=5000, force=True)
                page.wait_for_timeout(4500)
            except Exception as e:
                print(f'  x Click error: {e}')
                page.screenshot(path=os.path.join(OUT_DIR, f'err_{n:02d}.png'))
                continue

            # Verificar modal visible
            modal_text = page.evaluate(r'''() => {
                const all = [...document.querySelectorAll(".modal-dialog, .modal-content")];
                const vis = all.filter(el => {
                    const s = window.getComputedStyle(el);
                    return s.display !== "none" && s.visibility !== "hidden";
                });
                return { count: vis.length, text: vis[0]?.innerText?.substring(0, 200) || "" };
            }''')

            if modal_text.get('count', 0) == 0 or len(modal_text.get('text', '')) < 10:
                page.screenshot(path=os.path.join(OUT_DIR, f'nomodal_{n:02d}.png'))
                print(f'  x Modal no abrio')
                page.keyboard.press('Escape')
                page.wait_for_timeout(500)
                continue

            print(f'  ok Modal abierto')

            # Obtener UUID del modal
            uuid = ''
            modal_txt = modal_text.get('text', '')
            uuid_m = re.search(r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', modal_txt, re.I)
            if uuid_m:
                uuid = uuid_m.group(0)
            print(f'  UUID: {uuid or "no detectado"}')

            # Seleccionar primer radio
            try:
                rad = page.locator('.modal input[type=radio]').first
                if rad.count() > 0:
                    rad.click(timeout=2000)
                    page.wait_for_timeout(2500)
                    print(f'  ok Radio seleccionado')
            except Exception as e:
                print(f'  - Radio: {e}')

            page.wait_for_timeout(1500)

            # Screenshot del modal -> PDF via Pillow
            pdf_path = safe_name(nombre, 'ficha_oficial', 'pdf')
            try:
                modal_el = page.locator('.modal-content').first
                modal_el.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                img_bytes = modal_el.screenshot()
                img = Image.open(io.BytesIO(img_bytes))
                A4_W = 794
                iw, ih = img.size
                if iw != A4_W:
                    img = img.resize((A4_W, int(ih * A4_W / iw)), Image.LANCZOS)
                img.convert('RGB').save(pdf_path, 'PDF', resolution=150)
                size = os.path.getsize(pdf_path) // 1024
                print(f'  ok PDF: {os.path.basename(pdf_path)} ({size}KB)')
            except Exception as e:
                print(f'  x PDF error: {e}')
                pdf_path = None

            # Guardar imagen API
            foto_path = None
            if uuid and uuid in imgs_by_id:
                b64  = imgs_by_id[uuid]
                data = b64.split(',', 1)[1] if ',' in b64 else b64
                ext  = 'jpg' if '/jpeg' in b64 else 'png'
                foto_path = safe_name(nombre, 'foto', ext)
                with open(foto_path, 'wb') as f:
                    f.write(base64.b64decode(data))
                fsize = os.path.getsize(foto_path) // 1024
                print(f'  ok Foto: {os.path.basename(foto_path)} ({fsize}KB)')
            else:
                print(f'  - Sin foto')

            # Guardar JSON
            ameta = imgs_meta.get(uuid, {})
            persona = {
                'idvictima':     uuid or f'nouid_{n}',
                'idreporte':     ameta.get('idreporte', ''),
                'iddependencia': ameta.get('iddependencia', ''),
                'sexo_api':      ameta.get('sexo_api', ''),
                'nombre':        nombre,
                'edad_actual':   campos.get('Edad actual'),
                'fecha_hechos':  campos.get('Fecha de hechos'),
                'fecha_percato': campos.get('Fecha de percato'),
                'sexo':          campos.get('Sexo'),
                'estado':        campos.get('Estado'),
                'municipio':     campos.get('Municipio'),
                'fuente':        'RNPDNO / Comision Nacional de Busqueda',
                'url_portal':    PORTAL_URL,
                'foto_path':     foto_path,
                'ficha_pdf':     pdf_path,
            }
            json_path = safe_name(nombre, 'datos', 'json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(persona, f, ensure_ascii=False, indent=2)
            print(f'  ok JSON: {os.path.basename(json_path)}')
            resumen.append(persona)

            # Cerrar modal
            closed = False
            for sel in ['.icono-modal-cerrar', '.modal-header .close',
                        '.modal-header button', '[data-dismiss="modal"]']:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        btn.click(timeout=1000)
                        closed = True
                        break
                except:
                    pass
            if not closed:
                page.keyboard.press('Escape')
            page.wait_for_timeout(700)

        page.screenshot(path=os.path.join(OUT_DIR, '_screenshot.png'))
        browser.close()

    # Resumen
    with open(os.path.join(OUT_DIR, '_resumen.json'), 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    con_foto = sum(1 for p in resumen if p.get('foto_path'))
    con_pdf  = sum(1 for p in resumen if p.get('ficha_pdf') and p['ficha_pdf'] and os.path.exists(p['ficha_pdf']))
    print(f'\n{"="*60}')
    print(f'Personas:  {len(resumen)}')
    print(f'Con foto:  {con_foto}')
    print(f'Con PDF:   {con_pdf}')
    print(f'Carpeta:   {os.path.abspath(OUT_DIR)}')

if __name__ == '__main__':
    main()
