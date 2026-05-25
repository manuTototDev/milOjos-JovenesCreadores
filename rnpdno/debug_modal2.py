"""debug_modal2.py — inspecciona el texto exacto del modal-body"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(user_agent='Mozilla/5.0 Chrome/122')
    page.goto('https://consultapublicarnpdno.segob.gob.mx/consulta', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(2000)

    try:
        page.click('button.btn-busqueda-consulta', timeout=5000)
    except:
        pass
    page.wait_for_timeout(4000)

    # Primer botón de card con más información
    btns = page.locator('button').all()
    print(f'Total botones: {len(btns)}')
    for b in btns[:20]:
        try:
            txt = b.inner_text().strip()[:60]
            cls = b.get_attribute('class') or ''
            print(f'  "{txt}" cls={cls[:50]}')
        except:
            pass

    # Clic en primer "Más información"
    clicked = False
    for b in btns:
        try:
            txt = b.inner_text().strip()
            if 'nformaci' in txt or 'er m' in txt or 'etalle' in txt:
                b.click()
                clicked = True
                print(f'\nClickeado: "{txt}"')
                break
        except:
            pass

    if not clicked:
        print('No se encontró botón de info, clickeando primero disponible en cards')
        # Intentar cards directamente
        cards = page.locator('[class*="card"]').all()
        print(f'Cards: {len(cards)}')
        if cards:
            inner_btns = cards[0].locator('button, a').all()
            print(f'Botones en primera card: {len(inner_btns)}')
            for b in inner_btns:
                print(f'  "{b.inner_text().strip()[:50]}"')
            if inner_btns:
                inner_btns[-1].click()
                clicked = True

    page.wait_for_timeout(3000)

    # Leer modal-body
    try:
        modal_text = page.locator('.modal-body').inner_text()
        print(f'\n=== MODAL-BODY TEXT ===')
        print(modal_text[:1000])
    except Exception as e:
        print(f'Error leyendo modal-body: {e}')
        # Dump página completa post-click
        all_text = page.locator('body').inner_text()
        # Buscar sección de detalle
        idx = max(all_text.find('Edad'), all_text.find('Fecha'), all_text.find('Estado'))
        if idx > 0:
            print('POST-CLICK snippet:')
            print(all_text[max(0,idx-100):idx+500])

    browser.close()
