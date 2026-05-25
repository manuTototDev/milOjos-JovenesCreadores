"""
debug_modal.py — inspecciona el DOM del modal cuando se abre una ficha
"""
import json
from playwright.sync_api import sync_playwright

PORTAL_URL = 'https://consultapublicarnpdno.segob.gob.mx/consulta'

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)  # visible para ver qué pasa
    page    = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')

    page.goto(PORTAL_URL, wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(3000)

    # Click Buscar
    try:
        page.click('button:has-text("Buscar")', timeout=5000)
    except:
        page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

    # Dump de todos los elementos interactivos visibles
    dom_snapshot = page.evaluate('''() => {
        const all = [...document.querySelectorAll('button, a, [onclick]')];
        return all.slice(0,30).map(el => ({
            tag: el.tagName,
            text: el.innerText.substring(0,80).trim(),
            class: el.className.substring(0,60),
            href: el.getAttribute("href") || "",
        }));
    }''')
    print("=== BOTONES VISIBLES ===")
    for b in dom_snapshot:
        print(f'  {b["tag"]} "{b["text"]}" cls={b["class"][:40]}')

    # Intenta clic en primer botón de card
    first_card_btn = page.locator('.card button, .card a, [class*="card"] button, [class*="card"] a').first
    print(f'\nPrimer botón de card: {first_card_btn.count()} encontrados')
    if first_card_btn.count() > 0:
        first_card_btn.click()
        page.wait_for_timeout(3000)

        # Dump del DOM completo después del click
        all_text = page.evaluate('''() => document.body.innerText''')
        print("\n=== TEXTO COMPLETO POST-CLICK (800 chars) ===")
        print(all_text[:800])

        # Clases nuevas que aparecieron
        new_classes = page.evaluate('''() => {
            const els = [...document.querySelectorAll("*")];
            const classes = new Set();
            els.forEach(e => e.classList.forEach(c => classes.add(c)));
            return [...classes].filter(c => c.includes("modal") || c.includes("dialog") || c.includes("detalle") || c.includes("popup") || c.includes("overlay") || c.includes("drawer"));
        }''')
        print("\n=== CLASES DE MODAL ===")
        print(new_classes)

    browser.close()
