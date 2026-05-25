"""
debug_pdf_download.py
Explora exactamente qué petición de red se genera al hacer click en
"Descargar PDF" en el modal de RNPDNO para capturar su URL/payload.
"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page    = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')

    pdf_calls = []
    def on_request(req):
        url = req.url.lower()
        if any(x in url for x in ['pdf','ficha','boleti','report','descarg','generat']):
            pdf_calls.append({
                'method': req.method,
                'url':    req.url,
                'post':   req.post_data,
                'headers': dict(req.headers),
            })
        # También capturar todas las API calls
        if 'apiconsulta' in url:
            pdf_calls.append({
                'method': req.method,
                'url':    req.url,
                'post':   req.post_data,
            })

    all_responses = []
    def on_response(resp):
        if 'apiconsulta' in resp.url:
            try:
                body = json.loads(resp.body())
                post = json.loads(resp.request.post_data or '{}')
                ds = post.get('dataSend', {})
                all_responses.append({
                    'url': resp.url,
                    'action': ds.get('action', ds.get('idvictimadirecta','')),
                    'keys': list(body.get('result',{}).keys()) if body.get('result') else [],
                    'data_type': type(body.get('result',{}).get('data','')).__name__,
                    'data_100': str(body.get('result',{}).get('data',''))[:100],
                    'post_ds_keys': list(ds.keys()),
                })
            except:
                pass

    page.on('request', on_request)
    page.on('response', on_response)

    # Cargar portal
    print('Cargando...')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta',
              wait_until='networkidle', timeout=35000)
    page.wait_for_timeout(2000)
    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except:
        page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

    # Abrir primer modal público
    pub_cards = page.locator('div.card.ctn-card-consulta').all()
    for card_el in pub_cards:
        txt = card_el.inner_text()
        if 'CONFIDENCIAL' not in txt.upper() and 'INFORMACIÓN RESERVADA' not in txt.upper():
            card_el.click()
            break

    page.wait_for_timeout(3000)

    # Inspeccionar modal completo
    modal_html = page.evaluate(r'''() => {
        const m = document.querySelector(".modal.show, .modal[style*='block']");
        return m ? m.innerHTML.substring(0,3000) : "NO MODAL";
    }''')
    print('\n=== MODAL HTML (primeros 3000 chars) ===')
    print(modal_html[:2000])

    # Botones específicos
    btns = page.evaluate(r'''() => {
        const all = [...document.querySelectorAll("button, a, input[type=button], input[type=submit]")];
        return all.map(b => ({
            tag:     b.tagName,
            text:    b.innerText?.trim().substring(0,50) || "",
            cls:     b.className,
            href:    b.getAttribute("href") || "",
            onclick: b.getAttribute("onclick") || "",
            id:      b.id,
            visible: b.offsetParent !== null,
            type:    b.type || "",
        })).filter(b => b.visible);
    }''')
    print('\n=== BOTONES VISIBLES ===')
    for b in btns:
        print(f"  [{b['tag']}] '{b['text']}' cls={b['cls'][:40]} id={b['id']} href={b['href'][:60]}")

    # También revisar radio buttons
    radios = page.evaluate(r'''() => {
        const radios = [...document.querySelectorAll("input[type=radio], label")];
        return radios.slice(0,20).map(r => ({
            tag: r.tagName,
            text: r.innerText?.trim().substring(0,60) || "",
            value: r.value || "",
            checked: r.checked || false,
            cls: r.className,
        }));
    }''')
    print('\n=== RADIOS/LABELS ===')
    for r in radios:
        print(f"  [{r['tag']}] '{r['text']}' val={r['value']} checked={r['checked']}")

    # Seleccionar primer radio si existe
    try:
        first_radio = page.locator('input[type=radio]').first
        if first_radio.is_visible():
            first_radio.click()
            print('\n  → Radio seleccionado')
            page.wait_for_timeout(2000)
    except:
        pass

    # Buscar botón PDF y hacer click
    pdf_btn_found = page.evaluate(r'''() => {
        const btns = [...document.querySelectorAll("button, a, [class*=pdf]")];
        const pdf = btns.find(b => {
            const t = (b.innerText + b.className + (b.getAttribute("title")||"")).toLowerCase();
            return t.includes("pdf") || t.includes("descarg");
        });
        if (pdf) {
            const r = pdf.getBoundingClientRect();
            return { found: true, text: pdf.innerText, x: r.x + r.width/2, y: r.y + r.height/2, cls: pdf.className };
        }
        return { found: false };
    }''')
    print(f'\n=== BOTÓN PDF: {pdf_btn_found} ===')

    if pdf_btn_found.get('found'):
        print('  → Haciendo click en botón PDF...')
        page.mouse.click(pdf_btn_found['x'], pdf_btn_found['y'])
        page.wait_for_timeout(5000)

    print('\n=== API CALLS CAPTURADAS ===')
    for r in all_responses:
        print(f"  URL: {r['url'][:80]}")
        print(f"       action={r['action']} | ds_keys={r['post_ds_keys']} | data={r['data_100'][:60]}")

    print('\n=== PETICIONES PDF/DESCARGA CAPTURADAS ===')
    for r in pdf_calls:
        print(f"  [{r['method']}] {r['url']}")
        if r.get('post'):
            print(f"       POST: {r['post'][:300]}")

    browser.close()
