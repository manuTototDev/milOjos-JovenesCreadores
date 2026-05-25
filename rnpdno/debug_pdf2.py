"""
debug_pdf2.py — versión simplificada que detecta el botón PDF y su URL
Guarda resultados en debug_pdf2_output.json
"""
import json, sys
from playwright.sync_api import sync_playwright

out = {
    'pdf_calls': [],
    'api_calls': [],
    'visible_btns': [],
    'pdf_btn': None,
    'modal_snapshot': '',
}

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page    = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')

    def on_resp(resp):
        if 'apiconsulta' not in resp.url:
            return
        try:
            body = json.loads(resp.body())
            rs   = body.get('result', {})
            post = json.loads(resp.request.post_data or '{}')
            ds   = post.get('dataSend', {})
            data = rs.get('data', '')
            out['api_calls'].append({
                'url':       resp.url,
                'ds_keys':   list(ds.keys()),
                'idvictima': ds.get('idvictimadirecta',''),
                'action':    ds.get('action',''),
                'data_type': type(data).__name__,
                'data_start': str(data)[:200] if not isinstance(data, str) or not data.startswith('data:image') else 'BASE64_IMAGE',
                'result_keys': list(rs.keys()),
            })
        except Exception as e:
            out['api_calls'].append({'url': resp.url, 'error': str(e)})

    def on_req(req):
        url = req.url.lower()
        if any(x in url for x in ['pdf','ficha','report','descarg','boleti','print']):
            out['pdf_calls'].append({
                'method': req.method,
                'url': req.url,
                'post': req.post_data[:500] if req.post_data else None,
            })

    page.on('response', on_resp)
    page.on('request',  on_req)

    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta',
              wait_until='networkidle', timeout=35000)
    page.wait_for_timeout(2000)
    try:   page.click('button.btn-busqueda-consulta', timeout=5000)
    except: page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

    # Abrir primer modal público
    for card_el in page.locator('div.card.ctn-card-consulta').all():
        txt = card_el.inner_text()
        if 'CONFIDENCIAL' not in txt.upper():
            card_el.click()
            break
    page.wait_for_timeout(3000)

    # Snapshot del modal
    out['modal_snapshot'] = page.evaluate(r'''() => {
        const m = document.querySelector(".modal.show, .modal[style*=block]");
        return m ? m.innerText.substring(0, 600) : "NO MODAL";
    }''')

    # Todos los botones visibles
    out['visible_btns'] = page.evaluate(r'''() => {
        return [...document.querySelectorAll("button, a, [class*=pdf]")]
            .filter(b => b.offsetParent)
            .map(b => ({
                tag:  b.tagName,
                text: (b.innerText||"").trim().substring(0,60),
                cls:  b.className.substring(0,80),
                href: b.getAttribute("href")||"",
                id:   b.id||"",
            }));
    }''')

    # Seleccionar primer radio
    try:
        rad = page.locator('input[type=radio]').first
        if rad.count() > 0:
            rad.click(timeout=1000)
            page.wait_for_timeout(2000)
    except: pass

    # Buscar y hacer click en botón PDF
    out['pdf_btn'] = page.evaluate(r'''() => {
        const btns = [...document.querySelectorAll("button, a, [class*=pdf], [class*=descarg]")];
        const b = btns.find(x => {
            const t = ((x.innerText||"") + x.className + (x.getAttribute("title")||"")).toLowerCase();
            return t.includes("pdf") || t.includes("descarg");
        });
        if (!b) return null;
        const r = b.getBoundingClientRect();
        return { text: b.innerText, cls: b.className, x: r.x+r.width/2, y: r.y+r.height/2 };
    }''')

    if out['pdf_btn']:
        page.mouse.click(out['pdf_btn']['x'], out['pdf_btn']['y'])
        page.wait_for_timeout(4000)

    browser.close()

with open('rnpdno/debug_pdf2_output.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print('Guardado: rnpdno/debug_pdf2_output.json')
