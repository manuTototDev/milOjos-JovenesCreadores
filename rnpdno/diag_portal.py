"""diag_portal.py - diagnóstico rápido del portal RNPDNO"""
from playwright.sync_api import sync_playwright
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as pw:
    br = pw.chromium.launch(headless=False)
    ctx = br.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122')
    pg = ctx.new_page()
    pg.goto('https://consultapublicarnpdno.segob.gob.mx/consulta', wait_until='domcontentloaded', timeout=60000)
    pg.wait_for_timeout(7000)

    info = pg.evaluate('''() => {
        const btns = [...document.querySelectorAll("button")].map(b => ({
            text: b.innerText.trim().substring(0, 60),
            cls:  b.className.substring(0, 60),
        }));
        return {
            title:     document.title,
            url:       location.href,
            cardCount: document.querySelectorAll(".ctn-card-consulta").length,
            buttons:   btns,
            bodyText:  document.body.innerText.substring(0, 600),
        };
    }''')

    print(json.dumps(info, ensure_ascii=False, indent=2))
    pg.screenshot(path=os.path.join(BASE, 'diag_page.png'))

    # Si hay cards, intentar click en la primera y ver qué pasa
    if info.get('cardCount', 0) > 0:
        cards = pg.locator('.ctn-card-consulta').all()
        print(f'\nCards encontradas: {len(cards)}')
        links = cards[0].locator('a').all()
        print(f'Links en primera card: {len(links)}')
        if links:
            links[0].click(timeout=3000)
            pg.wait_for_timeout(3000)
            modal = pg.locator('.modal-content').count()
            print(f'Modal elements post-click: {modal}')
            pg.screenshot(path=os.path.join(BASE, 'diag_modal.png'))
    else:
        # Buscar botones de búsqueda
        print('\nNo hay cards. Intentando buscar...')
        for btn_txt in ['Buscar', 'BUSCAR', 'Consultar', 'Aceptar', 'Ver']:
            try:
                pg.get_by_text(btn_txt, exact=False).first.click(timeout=1000)
                pg.wait_for_timeout(3000)
                cnt = pg.locator('.ctn-card-consulta').count()
                if cnt > 0:
                    print(f'  ✓ Click "{btn_txt}" -> {cnt} cards')
                    break
            except:
                pass

    br.close()
print('Diagnóstico completo')
