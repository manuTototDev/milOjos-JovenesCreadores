"""
debug_ficha_oficial.py
Abre el modal de la primera persona pública e inspecciona:
  - Todos los botones disponibles
  - Llamadas de red que se generan al hacer click en "descarga"/"PDF"
  - URL o payload de la petición de generación de ficha
"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)   # visible para inspeccionar
    page = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')

    # Captura TODAS las peticiones
    reqs = []
    def on_req(req):
        if req.method in ('POST','GET') and ('api' in req.url or 'pdf' in req.url.lower() or 'ficha' in req.url.lower()):
            reqs.append({
                'method': req.method,
                'url':    req.url,
                'post':   req.post_data,
            })
    page.on('request', on_req)

    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta',
              wait_until='networkidle', timeout=35000)
    page.wait_for_timeout(2000)
    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except:
        page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

    # Abrir modal de la primera card pública
    pub_cards = page.locator('div.card.ctn-card-consulta').all()
    for card_el in pub_cards:
        txt = card_el.inner_text()
        if 'CONFIDENCIAL' not in txt.upper():
            card_el.click()
            break

    page.wait_for_timeout(3000)

    # Inspeccionar el modal
    modal_info = page.evaluate(r'''() => {
        const modal = document.querySelector(".modal.show, .modal[style*='display: block'], .modal-dialog");
        if (!modal) return { error: "No modal visible" };

        const btns = [...modal.querySelectorAll("button, a, [role='button']")];
        return {
            modalClass: modal.className,
            modalText: modal.innerText.substring(0, 800),
            buttons: btns.map(b => ({
                tag:  b.tagName,
                text: b.innerText.trim().substring(0, 60),
                cls:  b.className,
                href: b.getAttribute("href") || "",
                onclick: b.getAttribute("onclick") || "",
                dataTarget: b.getAttribute("data-target") || "",
                title: b.getAttribute("title") || "",
            }))
        };
    }''')

    print("=== MODAL INFO ===")
    print(json.dumps(modal_info, ensure_ascii=False, indent=2))

    # Buscar botones con texto de descarga/PDF
    print("\n=== BUSCANDO BOTÓN PDF/DESCARGA ===")
    pdf_btn = page.evaluate(r'''() => {
        const all = [...document.querySelectorAll("button, a, [role='button']")];
        return all
            .filter(b => {
                const t = (b.innerText + b.className + (b.getAttribute("title")||"")).toLowerCase();
                return t.includes("pdf") || t.includes("descarg") || t.includes("ficha") || 
                       t.includes("boleti") || t.includes("imprimir") || t.includes("print");
            })
            .map(b => ({
                tag:   b.tagName,
                text:  b.innerText.trim().substring(0, 60),
                cls:   b.className,
                href:  b.getAttribute("href") || "",
                title: b.getAttribute("title") || "",
                visible: b.offsetParent !== null,
            }));
    }''')
    print(json.dumps(pdf_btn, ensure_ascii=False, indent=2))

    # Tomar screenshot
    page.screenshot(path='rnpdno/debug_modal_screenshot.png')
    print("\nScreenshot: rnpdno/debug_modal_screenshot.png")

    # Esperar input del usuario para explorar
    page.wait_for_timeout(8000)

    print("\n=== PETICIONES CAPTURADAS ===")
    for r in reqs[-20:]:
        print(f"[{r['method']}] {r['url']}")
        if r['post']:
            print(f"  BODY: {r['post'][:200]}")

    browser.close()
