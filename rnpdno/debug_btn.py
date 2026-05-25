"""debug_btn.py — obtiene el texto exacto del botón de la primera card pública"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page    = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(2000)
    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except: pass
    page.wait_for_timeout(4000)

    # Información detallada de todas las tarjetas con sus botones
    data = page.evaluate(r'''() => {
        const cards = [...document.querySelectorAll("[class*='card']")];
        return cards.slice(0, 15).map((c, i) => {
            const btns = [...c.querySelectorAll("button, a")];
            return {
                i,
                cardClass: c.className,
                cardText: c.innerText.substring(0, 120),
                btns: btns.map(b => ({
                    tag:      b.tagName,
                    text:     b.innerText,
                    repr:     JSON.stringify(b.innerText),   // muestra chars especiales
                    cls:      b.className,
                    href:     b.getAttribute("href") || "",
                }))
            };
        });
    }''')

    with open('rnpdno/debug_btn_output.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Guardado: rnpdno/debug_btn_output.json")
    browser.close()
