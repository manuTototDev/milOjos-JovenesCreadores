import urllib.request
import re

url = 'https://consultapublicarnpdno.segob.gob.mx/assets/index-DiPcmp98.js'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=15) as r:
    js = r.read().decode('utf-8', errors='ignore')

print(f'JS size: {len(js):,} chars')

# Encontrar todas las URLs y rutas de API
api_urls = re.findall(r'https?://[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}(?:/[^\s"\'`>)]*)?', js)
unique = sorted(set(u.rstrip('/,;') for u in api_urls))
print('\n=== URLs de segob / api ===')
for u in unique:
    if 'segob' in u or 'apiconsulta' in u:
        print(u)

# Buscar rutas relativas de API (patrones /api/...)
api_paths = re.findall(r'["\'/](api/[a-zA-Z0-9/_-]+)["\'/]', js)
print('\n=== Rutas /api/ encontradas ===')
for p in sorted(set(api_paths)):
    print('/', p)

# Buscar palabras clave cerca de "fetch" o "axios"
for kw in ['pagina', 'pageid', 'token', 'folio', 'boletin', 'ficha', 'pdf']:
    idx = js.lower().find(kw)
    if idx > 0:
        snippet = js[max(0,idx-80):idx+120].replace('\n',' ')
        print(f'\n[{kw}] ...{snippet}...')
