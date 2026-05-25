import cv2
import serial
import time
import threading
import numpy as np
import os
import pickle
import re
import urllib.request
from collections import Counter
from PIL import Image
from insightface.app import FaceAnalysis

# --- CONFIGURACION DE RUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FCAES_DIR = os.path.join(BASE_DIR, "..", "fcaesDes", "fcaesDes")
DB_FILE = os.path.join(BASE_DIR, "face_database.pkl")
UPDATE_FILE = os.path.join(BASE_DIR, "last_update.txt")
CAPTURA_COMPLETA_DIR = os.path.join(BASE_DIR, "..", "capturas", "completas")
CAPTURA_ROSTRO_DIR = os.path.join(BASE_DIR, "..", "capturas", "rostros")

for d in [CAPTURA_COMPLETA_DIR, CAPTURA_ROSTRO_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# --- CLASE DE ACTUALIZACION AUTOMATICA ---
class BulletinManager:
    def __init__(self, db_file, update_file, fcaes_dir, app):
        self.db_file = db_file
        self.update_file = update_file
        self.fcaes_dir = fcaes_dir
        self.app = app
        self.database = []
        self.load_database()

    def load_database(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'rb') as f:
                self.database = pickle.load(f)
            print(f"Base de datos cargada: {len(self.database)} rostros.")
        else:
            print("Aviso: No se encontro base de datos inicial.")

    def check_and_update(self):
        ahora = time.time()
        last_upd = 0
        if os.path.exists(self.update_file):
            with open(self.update_file, 'r') as f:
                try: last_upd = float(f.read().strip())
                except: pass
        
        # Si paso mas de un dia (86400 seg)
        if ahora - last_upd > 86400:
            print("Buscando nuevos boletines en la web...")
            threading.Thread(target=self.run_update_process, daemon=True).start()

    def run_update_process(self):
        try:
            # 1. Descargar (Logica Simplificada de step1)
            target_url = "https://cobupem.edomex.gob.mx/boletines-personas-desaparecidas"
            req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                html = response.read().decode('utf-8')
            
            pattern = r'/sites/cobupem\.edomex\.gob\.mx/files/images/Desaparecidos/(\d{4})/[^/]+/[^"]+\.jpg'
            matches = re.findall(pattern, html)
            
            found_urls = re.findall(r'/sites/cobupem\.edomex\.gob\.mx/files/images/Desaparecidos/\d{4}/[^/]+/[^"]+\.jpg', html)
            base_url = "https://cobupem.edomex.gob.mx"
            
            new_files = []
            for partial_url in set(found_urls):
                url = base_url + partial_url
                year_match = re.search(r'/Desaparecidos/(\d{4})/', url)
                year = year_match.group(1) if year_match else "Desconocido"
                
                full_dir = os.path.join(self.fcaes_dir, year, "boletines_completos")
                if not os.path.exists(full_dir): os.makedirs(full_dir)
                
                filename = urllib.parse.unquote(os.path.basename(url))
                full_path = os.path.join(full_dir, filename)
                
                if not os.path.exists(full_path):
                    parts = url.split('/')
                    encoded_path = '/'.join([urllib.parse.quote(p) for p in parts[3:]])
                    encoded_url = f"https://{parts[2]}/{encoded_path}"
                    urllib.request.urlretrieve(encoded_url, full_path)
                    new_files.append((full_path, year, filename))
            
            if not new_files:
                print("No hay boletines nuevos.")
            else:
                print(f"Descargados {len(new_files)} nuevos boletines. Procesando...")
                for full_path, year, filename in new_files:
                    # 2. Crop (Logica de step2)
                    crop_dir = os.path.join(self.fcaes_dir, year, "fotos_recortadas")
                    if not os.path.exists(crop_dir): os.makedirs(crop_dir)
                    cropped_name = f"foto_{filename}"
                    cropped_path = os.path.join(crop_dir, cropped_name)
                    
                    try:
                        img_pil = Image.open(full_path)
                        # Box simplificado para el update
                        w, h = img_pil.size
                        box = (5, 60, 245, 380) if (w,h) == (640,480) else (int(w*0.02), int(h*0.1), int(w*0.5), int(h*0.8))
                        img_pil.crop(box).save(cropped_path)
                        
                        # 3. Index (Logica de step3)
                        img_cv = cv2.imread(cropped_path)
                        faces = self.app.get(img_cv)
                        if faces:
                            self.database.append({
                                'name': filename,
                                'year': year,
                                'embedding': faces[0].normed_embedding,
                                'original_path': cropped_path
                            })
                    except Exception as e:
                        print(f"Error procesando {filename}: {e}")
                
                # Guardar DB con prevencion de corrupcion
                tmp_db = self.db_file + ".tmp"
                with open(tmp_db, 'wb') as f:
                    pickle.dump(self.database, f)
                if os.path.exists(self.db_file): os.remove(self.db_file)
                os.rename(tmp_db, self.db_file)
                print(f"Base de datos actualizada. Total: {len(self.database)} rostros.")

            with open(self.update_file, 'w') as f:
                f.write(str(time.time()))
                
        except Exception as e:
            print(f"Error en el proceso de update: {e}")

# --- VIDEO STREAM ---
class VideoStream:
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.frame = None
        self.stopped = False

    def start(self):
        threading.Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            if ret:
                # El usuario rota la camara fisicamente 90 grados en su init.py original
                self.frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            else:
                self.stopped = True

    def read(self): return self.frame
    def stop(self): 
        self.stopped = True
        self.cap.release()

# --- INICIO SISTEMA ---
print("Cargando Modelos de IA (InsightFace)...")
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

manager = BulletinManager(DB_FILE, UPDATE_FILE, FCAES_DIR, app)
manager.check_and_update()

print("Conectando con Arduino...")
try:
    arduino = serial.Serial('COM6', 115200, timeout=0.01)
    time.sleep(2)
except:
    print("Aviso: No se encontro Arduino en COM6. Modo simulacion visual.")
    arduino = None

vs = VideoStream(1).start()

# --- AJUSTES MOVIMIENTO (MODO NERVIOSO) ---
posBase, posHombro, posCamV = 90.0, 60.0, 45.0
targetBase, targetCamV = 90.0, 45.0
ultimo_avistamiento = time.time()
ultima_foto = 0
last_known_base = 90.0
last_known_camv = 70.0



# --- BRAZO A (PCA canales 0-3) --- tracking principal ---
HOME_A = [90.0, 90.0, 90.0, 45.0]   # home segun arm_config.json
posA    = list(HOME_A)
targetA = list(HOME_A)

# Iniciamos otros brazos en reposo
b1 = [90, 60, 50, 90]
b3 = [90, 70, 60, 90]
b4 = [90, 65, 55, 90]

last_known_base = HOME_A[0]
last_known_camv = HOME_A[2]
current_display_indices = None
history = []
MAX_HISTORY = 15

# ── Rendering helpers ───────────────────────────────────────────────────────────
_BG     = (10,  10,  10 )
_GREEN  = (136, 255, 0  )   # #00ff88
_YELLOW = (0,   184, 255)   # #ffb800
_RED    = (45,  45,  255)   # #ff2d2d
_WHITE  = (232, 232, 232)
_DIM    = (55,  55,  55 )
_FONT   = cv2.FONT_HERSHEY_SIMPLEX

def _sc(pct):
    if pct > 60: return _GREEN
    if pct > 40: return _YELLOW
    return (80, 80, 80)

def _bracket(img, x, y, w, h, color=None, thick=2, L=20):
    """Corner-bracket bbox like milojos web UI."""
    if color is None: color = _GREEN
    for pts in [
        [(x,y+L),(x,y),(x+L,y)],
        [(x+w-L,y),(x+w,y),(x+w,y+L)],
        [(x+w,y+h-L),(x+w,y+h),(x+w-L,y+h)],
        [(x+L,y+h),(x,y+h),(x,y+h-L)],
    ]:
        for i in range(len(pts)-1):
            cv2.line(img, pts[i], pts[i+1], color, thick)

def _snoise(t, seed=0.0):
    """Smooth pseudo-random noise via layered sines (approx Perlin 1D)."""
    v  = np.sin(t*1.000 + seed)       * 1.000
    v += np.sin(t*2.137 + seed*1.73)  * 0.500
    v += np.sin(t*4.371 + seed*3.14)  * 0.250
    v += np.sin(t*9.113 + seed*5.29)  * 0.125
    return v / 1.875  # ~[-1, 1]

frame_n          = 0
last_blink       = time.time()
cursor_on        = True
last_sims        = None   # cached similarity scores for canvas
last_home_return = 0.0    # timestamp of last HOME snap during search
last_wild        = -4.0         # inicia en perlin mode de inmediato
wild_target      = list(HOME_A) # posicion salvaje actual
search_smooth    = 0.12         # suavizado durante busqueda normal
recog_mode       = False        # True durante animacion de reconocimiento
recog_start      = 0.0          # timestamp inicio de reconocimiento
RECOG_DUR        = 4.0          # 2s extender + 2s retraer
CENTERED_TH      = 0.20         # 20% del lado corto del frame

try:

    while True:
        frame = vs.read()
        if frame is None: continue

        faces = app.get(frame)
        ahora = time.time()
        frame_n += 1

        # Cursor blink
        if ahora - last_blink > 0.6:
            cursor_on  = not cursor_on
            last_blink = ahora
        cursor_char = '_' if cursor_on else ' '

        img_h, img_w = frame.shape[:2]
        cx, cy = img_w // 2, img_h // 2

        # Crosshair (dim)
        cv2.line(frame, (cx-14, cy), (cx+14, cy), (40,40,40), 1)
        cv2.line(frame, (cx, cy-14), (cx, cy+14), (40,40,40), 1)

        status_text  = 'SIN ROSTRO'
        status_color = _DIM
        visitor_line = ''

        if faces:
            ultimo_avistamiento = ahora
            main_face = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]), reverse=True)[0]

            bbox = main_face.bbox.astype(int)
            tx, ty = (bbox[0]+bbox[2])//2, (bbox[1]+bbox[3])//2

            err_x, err_y  = cx - tx, cy - ty
            distancia_px  = np.sqrt(err_x**2 + err_y**2)
            error_input   = np.array([err_x/(img_w/2), err_y/(img_h/2)])

            # Corner-bracket bbox
            bx, by = bbox[0], bbox[1]
            bw, bh = bbox[2]-bbox[0], bbox[3]-bbox[1]
            _bracket(frame, bx, by, bw, bh)
            cv2.putText(frame, 'ANALIZANDO', (bx, max(by-6,10)), _FONT, 0.3, _GREEN, 1)
            cv2.line(frame, (cx,cy),(tx,ty),(45,45,45),1)

            # ── DETECCION DE CENTRADO (20% del radio del frame) ────────────
            centrado = distancia_px < CENTERED_TH * min(img_w, img_h)

            if centrado:
                cv2.circle(frame, (tx, ty), 6, _GREEN, 1)          # punto verde centro
                _bracket(frame, bx, by, bw, bh, _GREEN, thick=2)   # bracket más grueso
                # Iniciar reconocimiento si no está activo y pasó suficiente tiempo
                if not recog_mode and (ahora - recog_start > RECOG_DUR + 2.0):
                    recog_mode  = True
                    recog_start = ahora

            if recog_mode:
                t_recog = ahora - recog_start
                if t_recog > RECOG_DUR:
                    recog_mode = False
                else:
                    # Sinusoide suave 0→1→0 sobre todo el ciclo
                    ef = np.sin(t_recog * np.pi / RECOG_DUR)
                    # S0: sigue horizontalmente pero más suave
                    targetA[0] += np.clip(err_x/(img_w/2)*2, -2, 2)
                    # S1 (arriba): baja para extender brazo hacia el frente
                    targetA[1]  = HOME_A[1] - 32 * ef
                    # S2 (horizonte): se extiende / retrae
                    targetA[2]  = HOME_A[2] + 38 * ef
                    # S3 (mano): compensa horizonte (inverso)
                    targetA[3]  = HOME_A[3] - 22 * ef
                    status_text  = 'RECONOCIENDO'
                    status_color = _GREEN
            else:
                # Tracking normal
                targetA[0] += np.clip(err_x/(img_w/2)*5, -5, 5)   # Base Yaw
                targetA[2] -= np.clip(err_y/(img_h/2)*5, -5, 5)   # Codo Tilt
                status_text  = 'CENTRADO' if centrado else 'ESCANEANDO'
                status_color = _GREEN

            if not recog_mode:
                gender       = 'MASC' if main_face.sex == 1 else 'FEM'
                visitor_line = f'{gender}  {int(main_face.age)} ANOS'

            # Guardar ultima posicion conocida
            last_known_base, last_known_camv = targetA[0], targetA[2]
            b1 = [180 - (targetA[0] - 5), targetA[2] + 15, targetA[2], 90]
            b3 = [targetA[0] + 5, targetA[2] - 10, targetA[2] + 10, 90]
            b4 = [180 - targetA[0], targetA[2] + 5, targetA[2] - 10, 90]

            # --- BUSQUEDA EN DB ---
            if manager.database:
                db_embs = np.array([e['embedding'] for e in manager.database])
                sims = np.dot(db_embs, main_face.normed_embedding)
                history.append(np.argmax(sims))
                if len(history) > MAX_HISTORY: history.pop(0)
                most_common_id, count = Counter(history).most_common(1)[0]
                if current_display_indices is None or (most_common_id != current_display_indices[0] and count >= 8):
                    current_display_indices = np.argsort(sims)[-8:][::-1]

                if current_display_indices is not None:
                    last_sims = sims   # cache for canvas render


            # Captura automatica (solo cuando centrado)
            if centrado:
                if ahora - ultima_foto > 10.0:
                    ultima_foto = ahora
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    cv2.imwrite(os.path.join(CAPTURA_COMPLETA_DIR, f"cam_{ts}.jpg"), frame)
                    print(f"SISTEMA: Captura centreada realizada ({ts})")

        else:
            # ── Modo busqueda ───────────────────────────────────────────
            tiempo_perdido = ahora - ultimo_avistamiento
            t_since_wild   = ahora - last_wild

            # Ciclo: 6s perlin → 3s salvaje → 1s HOME → repite (10s total)
            if t_since_wild > 10.0:
                last_wild    = ahora
                t_since_wild = 0.0
                # Wild target con servos correlacionados
                wb = float(np.random.uniform(20, 160))       # base random
                bd = wb - HOME_A[0]                          # desplazamiento
                wild_target = [
                    wb,
                    float(np.clip(HOME_A[1] + abs(bd)*0.55 + np.random.uniform(-18, 18), 20, 160)),  # arriba sube segun base
                    float(np.clip(HOME_A[2] - bd*0.45 + np.random.uniform(-22, 22), 20, 160)),       # horizonte contrabalance
                    HOME_A[3],
                ]

            if t_since_wild < 3.0:
                # ★ FASE SALVAJE (3 segundos)
                for i in range(4): targetA[i] = wild_target[i]
                status_text   = 'SALVAJE'
                status_color  = _RED
                search_smooth = 0.45

            elif t_since_wild < 4.0:
                # Regresa a HOME (1 segundo)
                for i in range(4): targetA[i] = HOME_A[i]
                status_text   = 'REGRESANDO'
                status_color  = _YELLOW
                search_smooth = 0.35

            else:
                # Perlin noise DINAMICO con servos correlacionados
                if ahora - last_home_return > 10.0:
                    last_home_return = ahora
                    for i in range(4): posA[i] = targetA[i] = HOME_A[i]

                # S0 (base): sweep rapido + burst agresivo
                base_x    = _snoise(ahora * 1.50, seed=0.0) * 60.0   # 1.5 Hz  ±60°
                fast_n    = _snoise(ahora * 5.50, seed=4.2)
                burst     = max(0.0, fast_n - 0.12) * 80.0            # bursts mas frecuentes y fuertes
                burst_dir = np.sign(_snoise(ahora * 4.10 + 11.0, seed=1.5))
                base_total = base_x + burst * burst_dir

                # S1 (arriba): sube con la base + movimiento propio rapido
                arriba_x  = abs(base_total) * 0.50 + _snoise(ahora * 1.10, seed=2.2) * 20.0

                # S2 (horizonte): contrabalance fuerte + noise propio agresivo
                horiz_x   = -base_total * 0.60 + _snoise(ahora * 1.30, seed=7.1) * 22.0

                targetA[0] = HOME_A[0] + base_total
                targetA[1] = HOME_A[1] + arriba_x
                targetA[2] = HOME_A[2] + horiz_x
                search_smooth = 0.18

                if tiempo_perdido < 3.0:
                    status_text  = 'BUSCANDO'
                    status_color = _YELLOW
                else:
                    status_text  = 'SIN ROSTRO'
                    status_color = _DIM

            t_misc = ahora * 0.25
            b1 = [HOME_A[0]+40*np.sin(t_misc), 60+5, 50, 90]
            b3 = [HOME_A[0]+40*np.cos(t_misc), 70, 60, 90]
            b4 = [HOME_A[0]+50*np.sin(t_misc*0.5), 65, 55, 90]

        # --- ENVIAR A PCA/ARDUINO (Brazo A = canales 0-3 primero) ---
        if arduino:
            f_smooth = 0.22 if faces else search_smooth
            for i in range(4):
                targetA[i] = np.clip(targetA[i], 20, 160)
                posA[i] += (targetA[i] - posA[i]) * f_smooth
                posA[i] = np.clip(posA[i], 20, 160)
            
            # Orden: Brazo A (ch 0-3), B (ch 4-7), C (ch 8-11), D (ch 12-15)
            cmd = f"${int(posA[0])},{int(posA[1])},{int(posA[2])},{int(posA[3])},"
            cmd += f"{int(b1[0])},{int(b1[1])},{int(b1[2])},{int(b1[3])},"
            cmd += f"{int(b3[0])},{int(b3[1])},{int(b3[2])},{int(b3[3])},"
            cmd += f"{int(b4[0])},{int(b4[1])},{int(b4[2])},{int(b4[3])},1\n"
            arduino.write(cmd.encode())

        # ── FRAME HUD ────────────────────────────────────────────────────────
        cv2.putText(frame, f'FRAME {str(frame_n).zfill(6)}', (8,14), _FONT, 0.28, (40,40,40), 1)
        if visitor_line:
            cv2.putText(frame, visitor_line, (img_w-128, 14), _FONT, 0.3, _GREEN, 1)
        cv2.circle(frame, (10, img_h-10), 3, status_color, -1)
        cv2.putText(frame, status_text, (18, img_h-6), _FONT, 0.3, status_color, 1)
        cv2.putText(frame, 'MIL OJOS v3.0', (img_w-110, img_h-6), _FONT, 0.28, (35,35,35), 1)

        # ── CANVAS — COINCIDENCIAS (4 cols x 2 rows = 8 tarjetas) ─────────────
        # Layout: card_w=143, gap=4, margin=4  → 4*(143+4)+4 = 596 ✓
        # card_h: photo=165 + label=30 = 195; rows: 78 + 195 + 4 + 195 + 22(footer) = 494
        _CW, _PH, _LH, _GAP, _MCOL = 143, 165, 30, 4, 4
        canvas = np.full((494, 600, 3), _BG, dtype=np.uint8)

        # Header
        cv2.putText(canvas, 'similitud facial / tiempo real', (12,16), _FONT, 0.28, _DIM, 1)
        cv2.putText(canvas, f'COINCIDENCIAS{cursor_char}', (12,46), _FONT, 0.68, _WHITE, 2)
        db_str = f'{len(manager.database):,}' if manager.database else '...'
        cv2.putText(canvas, 'BASE DE DATOS', (390,16), _FONT, 0.26, _DIM, 1)
        cv2.putText(canvas, db_str, (390,42), _FONT, 0.6, _WHITE, 2)
        cv2.putText(canvas, 'PERSONAS INDEXADAS', (390,55), _FONT, 0.24, _DIM, 1)
        cv2.line(canvas, (0,62),(600,62),(35,35,35),1)

        # Match cards — 4x2 grid (8 cards)
        if current_display_indices is not None and manager.database and last_sims is not None:
            for i, idx in enumerate(current_display_indices[:8]):
                m   = manager.database[idx]
                row, col = i//4, i%4
                x0  = _GAP + col*(_CW + _GAP)          # 4, 151, 298, 445
                y0  = 66   + row*(_PH + _LH + _GAP)    # row0=66, row1=265

                # Resolve image path
                img_path = m['original_path']
                if not os.path.exists(img_path):
                    fname = os.path.basename(img_path)
                    year  = m.get('year','')
                    img_path = os.path.join(FCAES_DIR, year, 'fotos_recortadas', fname)

                m_img = cv2.imread(img_path)
                if m_img is not None:
                    m_img = cv2.resize(m_img, (_CW, _PH))
                    canvas[y0:y0+_PH, x0:x0+_CW] = m_img
                    _bracket(canvas, x0, y0, _CW, _PH, _GREEN, thick=1, L=9)
                else:
                    cv2.rectangle(canvas,(x0,y0),(x0+_CW,y0+_PH),(18,18,18),-1)
                    cv2.rectangle(canvas,(x0,y0),(x0+_CW,y0+_PH),(32,32,32),1)
                    cv2.putText(canvas,'SIN FOTO',(x0+20,y0+82),_FONT,0.35,(45,45,45),1)

                # Score + rank ON photo (top strip)
                score_pct = int(float(last_sims[idx])*100)
                sc = _sc(score_pct)
                cv2.putText(canvas, f'#{i+1:02d}', (x0+2,y0+11), _FONT, 0.28, (60,60,60), 1)
                cv2.putText(canvas, f'{score_pct}%', (x0+_CW-34,y0+11), _FONT, 0.3, sc, 1)

                # Label below photo
                ly = y0+_PH
                cv2.rectangle(canvas,(x0,ly),(x0+_CW,ly+_LH),(14,14,14),-1)
                cv2.putText(canvas, m['name'][:18], (x0+2,ly+12), _FONT, 0.27, _WHITE, 1)
                cv2.putText(canvas, m.get('year',''), (x0+2,ly+24), _FONT, 0.23, _DIM, 1)
                # Score bar (1px)
                bw2 = int((_CW-4)*score_pct/100)
                cv2.rectangle(canvas,(x0+2,ly+27),(x0+2+bw2,ly+29),sc,-1)
                cv2.rectangle(canvas,(x0+2,ly+27),(x0+_CW-2,ly+29),(28,28,28),1)
        else:
            cv2.putText(canvas,'POSICIONATE FRENTE A LA CAMARA...',(30,290),_FONT,0.38,(45,45,45),1)

        # Footer
        cv2.line(canvas,(0,472),(600,472),(28,28,28),1)
        cv2.putText(canvas,'MIL OJOS - v3.0',(12,488),_FONT,0.26,(50,50,50),1)
        cv2.putText(canvas,time.strftime('%H:%M:%S'),(498,488),_FONT,0.26,(50,50,50),1)

        # ── DISPLAY ──────────────────────────────────────────────────────────
        cv2.imshow('MIL OJOS - Stream', cv2.resize(frame, (360, 480)))
        cv2.imshow('MIL OJOS - Coincidencias', canvas)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): break

except KeyboardInterrupt: pass
finally:
    vs.stop()
    cv2.destroyAllWindows()
    if arduino: arduino.close()