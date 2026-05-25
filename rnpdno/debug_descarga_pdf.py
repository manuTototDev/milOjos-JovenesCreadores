"""
debug_descarga_pdf.py
Hace click en "Descargar PDF" del modal RNPDNO e intercepta la descarga.
Estrategia: usar page.expect_download() para capturar el archivo PDF.
"""
import json, os, shutil
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR  = os.path.join(BASE_DIR, '..', 'rnpdno_data')
os.makedirs(OUT_DIR, exist_ok=True)

# Captura de todas las llamadas API
api_log = []

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 Chrome/122',
        accept_downloads=True,
    )
    page = ctx.new_page()

    def on_resp(resp):
        if 'apiconsulta' not in resp.url:
            return
        try:
            body = json.loads(resp.body())
            rs   = body.get('result', {})
            post = json.loads(resp.request.post_data or '{}')
            ds   = post.get('dataSend', {})
            data = rs.get('data', '')
            is_img = isinstance(data, str) and data.startswith('data:image')
            api_log.append({
                'url':        resp.url,
                'ds_keys':    list(ds.keys()),
                'idvictima':  ds.get('idvictimadirecta', ''),
                'idreporte':  ds.get('idreporte', ''),
                'iddep':      ds.get('iddependenciaorigen', ''),
                'sexo':       ds.get('sexo', ''),
                'data_type':  'IMAGE' if is_img else type(data).__name__,
                'data_prev':  '' if is_img else str(data)[:300],
                'result_ok':  rs.get('success', ''),
            })
        except Exception as e:
            api_log.append({'url': resp.url, 'error': str(e)})

    page.on('response', on_resp)

    print('Cargando portal...')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta',
              wait_until='networkidle', timeout=35000)
    page.wait_for_timeout(2000)
    try:   page.click('button.btn-busqueda-consulta', timeout=5000)
    except: page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

    # Abrir modal de primera card pública
    for card_el in page.locator('div.card.ctn-card-consulta').all():
        txt = card_el.inner_text()
        if 'CONFIDENCIAL' not in txt.upper():
            print(f'Abriendo modal de: {txt.split(chr(10))[0].strip()[:50]}')
            card_el.click()
            break
    page.wait_for_timeout(3000)

    # Seleccionar primer radio/reporte
    try:
        rad = page.locator('input[type=radio]').first
        if rad.count() > 0:
            rad.click(timeout=2000)
            page.wait_for_timeout(2500)
            print('  Radio seleccionado')
    except: pass

    # Buscar botón descarga PDF
    pdf_info = page.evaluate(r'''() => {
        const all = [...document.querySelectorAll("button, a, span, div")];
        return all
            .filter(b => b.offsetParent && ((b.innerText||"").toLowerCase().includes("descarg") || 
                                             (b.className||"").toLowerCase().includes("pdf") ||
                                             (b.innerText||"").toLowerCase().includes("pdf")))
            .map(b => {
                const r = b.getBoundingClientRect();
                return {
                    tag: b.tagName, text: (b.innerText||"").trim().substring(0,40),
                    cls: b.className.substring(0,60), 
                    id:  b.id, href: b.getAttribute("href")||"",
                    x: r.x + r.width/2, y: r.y + r.height/2,
                    rect: {x: r.x, y: r.y, w: r.width, h: r.height}
                };
            });
    }''')

    print(f'\nBotones PDF/Descarga encontrados: {len(pdf_info)}')
    for b in pdf_info:
        print(f"  [{b['tag']}] '{b['text']}' cls={b['cls'][:40]} href={b['href']}")

    # Intentar descarga via page.expect_download
    pdf_saved = None
    for btn in pdf_info:
        if 'descarg' in (btn['text'] + btn['cls']).lower():
            print(f'\nHaciendo click en "{btn["text"]}" ({btn["x"]:.0f},{btn["y"]:.0f})...')
            try:
                with page.expect_download(timeout=10000) as dl_info:
                    page.mouse.click(btn['x'], btn['y'])
                dl = dl_info.value
                dest = os.path.join(OUT_DIR, 'ficha_oficial_test.pdf')
                dl.save_as(dest)
                pdf_saved = dest
                print(f'  ✓ PDF descargado: {dest} ({os.path.getsize(dest)//1024}KB)')
            except Exception as e:
                print(f'  ✗ No se pudo descargar via expect_download: {e}')
                # El PDF puede generarse via POST que devuelve base64 o blob
                # esperar y revisar las API calls
                page.wait_for_timeout(5000)
            break

    browser.close()

print(f'\n=== API CALLS ({len(api_log)}) ===')
for c in api_log:
    print(f"  keys={c.get('ds_keys',[])} idv={c.get('idvictima','')[:12]} "
          f"type={c.get('data_type','')} ok={c.get('result_ok','')} "
          f"prev={c.get('data_prev','')[:80]}")

# Guardar log completo
with open('rnpdno/api_log.json', 'w', encoding='utf-8') as f:
    json.dump(api_log, f, ensure_ascii=False, indent=2)
print('\nLog guardado: rnpdno/api_log.json')
