import pickle, sys

db = pickle.load(open('face_database.pkl', 'rb'))
sys.stdout.reconfigure(encoding='utf-8')

print(f'Total rostros en DB: {len(db)}')
print('\nKeys de una entrada:', list(db[0].keys()))
print('\n--- Primeras 15 entradas ---')
for e in db[:15]:
    print(repr(e.get('name','?')), '|', e.get('year','?'), '|', repr(e.get('original_path','?'))[-60:])

# Verificar si hay campos extra en algunas entradas
all_keys = set()
for e in db:
    all_keys.update(e.keys())
print('\nTodos los campos existentes en la DB:', all_keys)

# Muestra un path completo para ver la estructura
print('\nPath completo ejemplo:')
print(db[0].get('original_path','?'))
print(db[100].get('original_path','?'))
