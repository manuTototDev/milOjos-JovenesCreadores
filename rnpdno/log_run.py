"""log_run.py — captura la salida completa del scraper a un archivo de log"""
import sys, io

# Redirigir stdout a archivo Y consola
class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            try: f.write(obj)
            except: pass
    def flush(self):
        for f in self.files:
            try: f.flush()
            except: pass

log_file = open('rnpdno/scraper_log.txt', 'w', encoding='utf-8')
sys.stdout = Tee(sys.__stdout__, log_file)
sys.stderr = Tee(sys.__stderr__, log_file)

# Ejecutar el scraper inline para no perder el output
import importlib.util, os
spec = importlib.util.spec_from_file_location('scraper', 'rnpdno/rnpdno_scraper.py')
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main()

log_file.close()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print('Log guardado en rnpdno/scraper_log.txt')
