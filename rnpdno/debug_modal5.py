"""debug_modal5.py — guarda el modal text a archivo"""
import json, sys
from playwright.sync_api import sync_playwright

results = {}

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(2000)
    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except: pass
    page.wait_for_timeout(4000)

    cards = page.locator('[class*="card"]').all()

    # Procesa las 5 primeras cards con botón
    count = 0
    for i, c in enumerate(cards):
        if count >= 5: break
        btns = c.locator('button, a').all()
        if not btns: continue

        btn_text = btns[0].inner_text().strip()
        card_text = c.inner_text().strip()
        print(f'[{i}] card="{card_text[:60]}" btn="{btn_text}"')

        btns[0].click()
        page.wait_for_timeout(3000)

        modal_text = ''
        try:
            modal = page.locator('.modal-body')
            modal.wait_for(state='visible', timeout=5000)
            modal_text = modal.inner_text()
        except Exception as e:
            print(f'  Error modal: {e}')

        results[f'card_{i}'] = {
            'card_preview': card_text[:200],
            'modal_text': modal_text,
        }

        # Cerrar modal
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(800)
        except: pass

        count += 1

    browser.close()

with open('rnpdno/debug_modal_texts.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print('Guardado: rnpdno/debug_modal_texts.json')
