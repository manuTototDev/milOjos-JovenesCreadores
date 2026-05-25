"""
rnpdno_scraper.py — v9
Solución al problema de matching:
  - Las fotos se precargan al buscar (no se disparan por click individual)
  - El matching correcto usa: sexo_api + orden de aparición en las cards públicas
  - Pero lo más fiable: forzar reload antes de cada click para obtener respuesta limpia

Alternativa más simple y confiable:
  1. Cargar la página y buscar → captura TODOS los callbacks de imagen
  2. Leer el DOM para saber el ORDEN en que aparecen las cards públicas
  3. Asignar las imágenes por ORDEN DE CARGA (que coincide con el orden de la lista)
  4. Validar con sexo_api vs sexo del DOM

Uso:
    python rnpdno_scraper.py
"""
import os, json, base64
from playwright.sync_api import sync_playwright

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(BASE_DIR, '..', 'rnpdno_data')
PORTAL_URL = 'https://consultapublicarnpdno.segob.gob.mx/consulta'
MAX_ITEMS  = 10

def guardar_img(b64_str: str, path: str) -> str | None:
    try:
        data = b64_str.split(',', 1)[1] if ',' in b64_str else b64_str
        ext  = 'jpg' if '/jpeg' in b64_str else 'png'
        out  = f'{path}_foto.{ext}'
        with open(out, 'wb') as f:
            f.write(base64.b64decode(data))
        return out
    except Exception as e:
        print(f'  [img-err] {e}')
        return None

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f'Salida  = {os.path.abspath(OUT_DIR)}')
    print(f'Límite  = {MAX_ITEMS}\n')

    # Captura global de todas las imágenes y sus metadatos
    # clave: idvictima, valor: {b64, meta}
    imgs_by_id: dict[str, dict] = {}
    imgs_order: list[str] = []   # orden en que llegaron del API

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent='Mozilla/5.0 Chrome/122')
        page = ctx.new_page()

        # Interceptor global — captura TODAS las imágenes
        def on_response(resp):
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
                if not (isinstance(inner, str) and inner.startswith('data:image')):
                    return
                req_body = json.loads(resp.request.post_data or '{}')
                ds  = req_body.get('dataSend', {})
                vid = ds.get('idvictimadirecta', '')
                if vid and vid not in imgs_by_id:
                    imgs_by_id[vid] = {
                        'b64':           inner,
                        'idreporte':     ds.get('idreporte', ''),
                        'iddependencia': ds.get('iddependenciaorigen', ''),
                        'sexo_api':      ds.get('sexo', ''),
                    }
                    imgs_order.append(vid)
                    print(f'  [IMG] {vid[:20]} {ds.get("sexo","")}')
            except Exception:
                pass

        page.on('response', on_response)

        # Cargar portal
        print('Cargando portal...')
        page.goto(PORTAL_URL, wait_until='networkidle', timeout=35000)
        page.wait_for_timeout(2000)
        try:
            page.click('button.btn-busqueda-consulta', timeout=5000)
        except:
            page.keyboard.press('Enter')
        page.wait_for_timeout(5000)  # dar tiempo a que precarguen las imágenes

        # Click en cada card pública para asegurar carga de imagen
        pub_cards = page.locator('div.card.ctn-card-consulta').all()
        clicked = 0
        for card_el in pub_cards:
            if clicked >= MAX_ITEMS:
                break
            try:
                txt = card_el.inner_text()
                if 'CONFIDENCIAL' in txt.upper() or 'INFORMACIÓN RESERVADA' in txt.upper():
                    continue
                card_el.scroll_into_view_if_needed()
                card_el.click()
                page.wait_for_timeout(2000)
                # Cerrar modal
                try:
                    page.locator('.icono-modal-cerrar, .modal-header .close, button.close').first.click(timeout=800)
                except:
                    try: page.keyboard.press('Escape')
                    except: pass
                page.wait_for_timeout(300)
                clicked += 1
            except Exception:
                pass

        # Leer datos de cards del DOM (después de los clicks)
        print('\nLeyendo cards del DOM...')
        cards_dom = page.evaluate(r'''() => {
            const cards = [...document.querySelectorAll("div.card.ctn-card-consulta")];
            return cards.map(card => {
                const titulo   = (card.querySelector(".texto-card-consulta") || card.querySelector(".ctn-titulos-card-consulta"))?.innerText.trim() || "";
                const completo = card.querySelector(".texto-complemetario-card")?.innerText.trim() || "";
                const esConf   = titulo.toUpperCase().includes("CONFIDENCIAL") ||
                                 titulo === "" ||
                                 card.innerText.toUpperCase().includes("INFORMACIÓN RESERVADA");
                const campos   = {};
                completo.split("\n").forEach(line => {
                    const m = line.match(/^([^:]+):\s*(.+)$/);
                    if (m) campos[m[1].trim()] = m[2].trim();
                });
                return {
                    nombre:       titulo,
                    confidencial: esConf,
                    campos,
                    sexo_dom:     campos["Sexo"] || "",
                };
            });
        }''')

        page.screenshot(path=os.path.join(OUT_DIR, '_screenshot.png'))
        browser.close()

    publicas = [c for c in cards_dom if not c['confidencial'] and c['nombre']]
    print(f'\nCards públicas: {len(publicas)}')
    print(f'Imágenes API:   {len(imgs_by_id)}')

    # ── Matching inteligente ──────────────────────────────────────
    # Las imágenes llegan en el mismo orden que las cards públicas
    # ya que el portal las carga secuencialmente al renderizar la lista.
    # Validación adicional: sexo_api debe coincidir con sexo_dom.

    # Construir lista de imgs ordenadas
    imgs_list = [imgs_by_id[vid] for vid in imgs_order]

    # Intentar match con validación de sexo
    matched: list[tuple] = []  # (card_data, img_data_or_None, idvictima)

    img_pool    = list(zip(imgs_order, imgs_list))  # [(vid, img_data), ...]
    img_used    = set()

    for card in publicas[:MAX_ITEMS]:
        sexo_dom = card.get('sexo_dom', '').upper()
        best_vid = None
        best_img = None

        # Buscar primera imagen no usada que coincida en sexo
        for vid, img_data in img_pool:
            if vid in img_used:
                continue
            if sexo_dom and img_data['sexo_api'] and sexo_dom != img_data['sexo_api']:
                continue  # sexo no coincide, saltar
            best_vid = vid
            best_img = img_data
            break

        # Si no hay match de sexo, tomar la siguiente no usada
        if best_vid is None:
            for vid, img_data in img_pool:
                if vid in img_used:
                    continue
                best_vid = vid
                best_img = img_data
                break

        if best_vid:
            img_used.add(best_vid)

        matched.append((card, best_img, best_vid))

    # ── Guardar resultados ────────────────────────────────────────
    resumen = []
    for i, (card, img_data, vid) in enumerate(matched, 1):
        campos    = card['campos']
        vid_clean = vid or f'noid_{i}'
        short     = vid_clean.replace('-','')[:18]
        prefix    = os.path.join(OUT_DIR, f'{i:02d}_{short}')

        foto_path = None
        if img_data and img_data.get('b64'):
            foto_path = guardar_img(img_data['b64'], prefix)
            size = os.path.getsize(foto_path)//1024 if foto_path and os.path.exists(foto_path) else 0
            print(f'  [{i:02d}] {card["nombre"]} | {campos.get("Estado","?")} | '
                  f'IMG {size}KB | sexo_api={img_data.get("sexo_api","")} dom={card["sexo_dom"]}')
        else:
            print(f'  [{i:02d}] {card["nombre"]} | {campos.get("Estado","?")} | SIN FOTO')

        persona = {
            'idvictima':     vid_clean,
            'idreporte':     (img_data or {}).get('idreporte', ''),
            'iddependencia': (img_data or {}).get('iddependencia', ''),
            'sexo_api':      (img_data or {}).get('sexo_api', ''),
            'nombre':        card['nombre'],
            'edad_actual':   campos.get('Edad actual'),
            'fecha_hechos':  campos.get('Fecha de hechos'),
            'fecha_percato': campos.get('Fecha de percato'),
            'sexo':          campos.get('Sexo'),
            'estado':        campos.get('Estado'),
            'municipio':     campos.get('Municipio'),
            'estatura':      campos.get('Estatura'),
            'complexion':    campos.get('Complexión', campos.get('Complexion')),
            'color_piel':    campos.get('Color de piel'),
            'cabello':       campos.get('Cabello'),
            'fuente':        'RNPDNO / Comision Nacional de Busqueda',
            'url_portal':    PORTAL_URL,
            'foto_path':     foto_path,
        }

        with open(f'{prefix}.json', 'w', encoding='utf-8') as f:
            json.dump(persona, f, ensure_ascii=False, indent=2)
        resumen.append(persona)

    with open(os.path.join(OUT_DIR, '_resumen.json'), 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    con_foto = sum(1 for p in resumen if p.get('foto_path'))
    print(f'\n{"="*60}')
    print(f'Guardadas: {len(resumen)} | Con foto: {con_foto}')
    print(f'Carpeta:   {os.path.abspath(OUT_DIR)}')

if __name__ == '__main__':
    main()
