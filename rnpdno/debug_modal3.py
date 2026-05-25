"""debug_modal3.py"""
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
    print(f'Cards: {len(cards)}')

    # Información de la primera card
    c = cards[4]  # la 5ta, que debería ser la pública (MARCOS OBED)
    print('Card HTML (primeros 600):')
    print(c.inner_text()[:400])

    # Botones en esa card
    btns = c.locator('button, a').all()
    print(f'\nBotones: {len(btns)}')
    for b in btns:
        print(f'  text="{b.inner_text().strip()[:60]}" cls="{b.get_attribute("class") or ""}"')

    # Click en la card directamente
    c.click()
    page.wait_for_timeout(3000)

    # Ahora leer el modal
    try:
        modal = page.locator('.modal-body')
        modal.wait_for(state='visible', timeout=5000)
        text = modal.inner_text()
        print(f'\n=== MODAL-BODY ===')
        print(text[:800])
    except Exception as e:
        print(f'Error: {e}')
        # Intentar leer cualquier overlay
        body = page.locator('body').inner_text()
        idx = body.find('Edad actual')
        if idx < 0: idx = body.find('Fecha de hechos')
        print('Body snippet:', body[max(0,idx-50):idx+400] if idx >= 0 else body[:300])

    browser.close()
