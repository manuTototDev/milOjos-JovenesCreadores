"""debug_cards.py — diagnóstico rápido de cards y botones"""
from playwright.sync_api import sync_playwright
import json

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page    = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(2000)
    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except: pass
    page.wait_for_timeout(4000)

    # Diagnóstico via evaluate en toda la página
    info = page.evaluate('''() => {
        const cards = [...document.querySelectorAll("[class*='card']")];
        const result = cards.slice(0,10).map((c, i) => {
            const btns = [...c.querySelectorAll("button, a")];
            const hasInfo = btns.some(b => b.innerText.toUpperCase().includes("INFORMACI"));
            return {
                index: i,
                text: c.innerText.substring(0, 80).replace(/\\n/g, "│"),
                numBtns: btns.length,
                btnTexts: btns.map(b => b.innerText.trim().substring(0, 40)),
                hasInfoBtn: hasInfo,
                cardClass: c.className.substring(0, 60),
            };
        });
        return result;
    }''')

    for r in info:
        print(f"[{r['index']}] hasInfo={r['hasInfoBtn']} btns={r['numBtns']} cls={r['cardClass'][:40]}")
        print(f"    text: {r['text'][:80]}")
        if r['btnTexts']:
            print(f"    btnTexts: {r['btnTexts']}")

    # También: cuántas tienen botón de info en total
    totals = page.evaluate('''() => {
        const cards = [...document.querySelectorAll("[class*='card']")];
        const withInfo = cards.filter(c => 
            [...c.querySelectorAll("button, a")].some(b => b.innerText.toUpperCase().includes("INFORMACI"))
        );
        return { total: cards.length, withInfo: withInfo.length };
    }''')
    print(f"\nTotal cards: {totals['total']} | Con botón INFO: {totals['withInfo']}")

    # Obtener la info de todas las cards con botón
    all_public = page.evaluate('''() => {
        const cards = [...document.querySelectorAll("[class*='card']")];
        return cards
            .filter(c => [...c.querySelectorAll("button, a")].some(b => b.innerText.toUpperCase().includes("INFORMACI")))
            .slice(0,5)
            .map(c => ({
                text: c.innerText.substring(0, 150).replace(/\\n/g, "│"),
                btnTexts: [...c.querySelectorAll("button, a")].map(b => b.innerText.trim()),
            }));
    }''')
    print("\n=== CARDS PÚBLICAS (primeras 5) ===")
    for i, c in enumerate(all_public):
        print(f"[{i}] {c['text'][:100]}")
        print(f"    btns: {c['btnTexts']}")

    browser.close()
