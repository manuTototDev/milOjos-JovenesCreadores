"""debug_modal4.py — encuentra cards públicas y lee el modal"""
import sys
from playwright.sync_api import sync_playwright

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
    sys.stdout.write(f'Cards totales: {len(cards)}\n')

    # Encuentra la primera card CON botón (pública)
    found_idx = -1
    for i, c in enumerate(cards[:20]):
        txt = c.inner_text().strip()[:100]
        btns = c.locator('button, a').count()
        sys.stdout.write(f'  [{i}] btns={btns} text="{txt[:80]}"\n')
        if btns > 0 and found_idx < 0:
            found_idx = i

    sys.stdout.write(f'\nCard pública encontrada: índice {found_idx}\n')
    sys.stdout.flush()

    if found_idx >= 0:
        # click la card pública
        cards[found_idx].click()
        page.wait_for_timeout(3500)

        # Leer modal
        try:
            modal = page.locator('.modal-body')
            modal.wait_for(state='visible', timeout=5000)
            text = modal.inner_text()
            sys.stdout.write(f'\n=== MODAL-BODY TEXT ===\n')
            sys.stdout.write(text[:1200])
            sys.stdout.write('\n')
        except Exception as e:
            sys.stdout.write(f'Error modal: {e}\n')
            body_text = page.locator('body').inner_text()
            idx = max(body_text.find('Edad actual'), body_text.find('Fecha de hechos'))
            if idx >= 0:
                sys.stdout.write('BODY SNIPPET:\n')
                sys.stdout.write(body_text[max(0,idx-200):idx+800])

    sys.stdout.flush()
    browser.close()
