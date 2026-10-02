#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sistema.py - MIL OJOS
===============================================================
Sistema completo: N brazos, cada uno con su camara, cotejando rostros
contra la base de datos de personas desaparecidas.

El bus USB 2.0 no da para tener todas las camaras abiertas a la vez, asi
que se mantiene una VENTANA de 3 camaras abiertas y se rota. La rotacion
respeta a quien esta viendo un rostro: una camara con alguien enfrente no
se cierra aunque le toque turno.

El brazo cuya camara esta cerrada no se queda congelado: sigue con su
vagabundeo suave dentro de su zona segura calibrada.

Requiere:
    config/camaras.json    -> de emparejar_camaras.py  (CADUCA al reiniciar)
    config/brazo_N.json    -> de calibrar_brazos.py
    face_database.pkl      -> base de rostros indexada

Uso:
    python sistema.py --puerto COM6
    python sistema.py --puerto COM6 --abiertas 3 --rotacion 8
    python sistema.py --sin-arduino          # solo vision, sin mover nada
===============================================================
"""

import argparse
import json
import os
import pickle
import sys
import threading
import time
from collections import Counter

import cv2
import numpy as np

from calibrar_brazos import (
    DIR_CONFIG, SERVOS_POR_BRAZO, angulo_fisico, cargar_config,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "face_database.pkl")
FCAES_DIR = os.path.join(BASE_DIR, "..", "fcaesDes", "fcaesDes")
CAPTURAS_DIR = os.path.join(BASE_DIR, "..", "capturas", "completas")
RUTA_CAMARAS = os.path.join(DIR_CONFIG, "camaras.json")

# --- parametros de operacion ---
ANCHO, ALTO = 640, 480
DET_SIZE = (320, 320)        # mas chico que 640 = mas FPS en CPU
ROTAR_90 = True              # las camaras van montadas de lado
SEG_ROTACION = 8.0           # cada cuanto rota la ventana
GRACIA_ROSTRO = 4.0          # no cerrar una camara que vio rostro hace menos
SEG_CAPTURA = 10.0           # minimo entre fotos guardadas
MAX_HISTORY = 15

# --- paleta (misma del init.py) ---
_BG     = (10, 10, 10)
_GREEN  = (136, 255, 0)
_YELLOW = (0, 184, 255)
_RED    = (45, 45, 255)
_WHITE  = (232, 232, 232)
_DIM    = (55, 55, 55)
_FONT   = cv2.FONT_HERSHEY_SIMPLEX


# ===============================================================
# Camara con hilo propio
# ===============================================================
class CamaraHilo:
    """Captura en su propio hilo. Se abre y se cierra segun la ventana."""

    def __init__(self, indice, brazo):
        self.indice = indice
        self.brazo = brazo
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.corriendo = False
        self.hilo = None
        self.abierta_desde = 0.0
        self.ultimo_rostro = 0.0
        self.fps = 0.0
        self._n = 0
        self._t0 = 0.0

    def abrir(self):
        if self.corriendo:
            return True
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(self.indice, backend)
        if not self.cap.isOpened():
            self.cap = None
            return False
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass
        self.corriendo = True
        self.abierta_desde = time.time()
        self._t0 = time.time()
        self._n = 0
        self.hilo = threading.Thread(target=self._bucle, daemon=True)
        self.hilo.start()
        return True

    def _bucle(self):
        while self.corriendo and self.cap is not None:
            ok, img = self.cap.read()
            if not ok or img is None:
                time.sleep(0.02)
                continue
            if ROTAR_90:
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            with self.lock:
                self.frame = img
            self._n += 1
            dt = time.time() - self._t0
            if dt >= 1.0:
                self.fps = self._n / dt
                self._n = 0
                self._t0 = time.time()

    def leer(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def cerrar(self):
        self.corriendo = False
        if self.hilo is not None:
            self.hilo.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        with self.lock:
            self.frame = None


class GestorCamaras:
    """Mantiene abiertas como maximo N camaras y rota entre las demas."""

    def __init__(self, mapeo, max_abiertas=3, seg_rotacion=SEG_ROTACION):
        # mapeo: lista de (brazo, indice_cv2)
        self.camaras = [CamaraHilo(idx, br) for br, idx in mapeo]
        self.max_abiertas = min(max_abiertas, len(self.camaras))
        self.seg_rotacion = seg_rotacion
        self.ultima_rotacion = 0.0
        self.turno = 0

        for c in self.camaras[:self.max_abiertas]:
            c.abrir()
        self.ultima_rotacion = time.time()

    @property
    def abiertas(self):
        return [c for c in self.camaras if c.corriendo]

    @property
    def cerradas(self):
        return [c for c in self.camaras if not c.corriendo]

    def paso(self):
        """Rota la ventana si toca. Respeta a quien esta viendo un rostro."""
        ahora = time.time()
        if len(self.camaras) <= self.max_abiertas:
            return None                      # caben todas, no hay que rotar
        if ahora - self.ultima_rotacion < self.seg_rotacion:
            return None

        cerradas = self.cerradas
        if not cerradas:
            return None

        # candidata a cerrar: la que lleva mas tiempo abierta y NO vio rostro
        # hace poco. Si todas estan viendo rostros, no rotamos.
        candidatas = [c for c in self.abiertas
                      if ahora - c.ultimo_rostro > GRACIA_ROSTRO]
        if not candidatas:
            self.ultima_rotacion = ahora     # reintenta en el siguiente ciclo
            return None

        saliente = min(candidatas, key=lambda c: c.abierta_desde)
        entrante = cerradas[self.turno % len(cerradas)]
        self.turno += 1

        saliente.cerrar()
        if not entrante.abrir():
            saliente.abrir()                 # si la nueva no abre, deshacemos
            self.ultima_rotacion = ahora
            return None

        self.ultima_rotacion = ahora
        return (saliente.brazo, entrante.brazo)

    def cerrar_todo(self):
        for c in self.camaras:
            c.cerrar()


# ===============================================================
# Brazos
# ===============================================================
def _snoise(t, seed=0.0):
    """Ruido suave por senos superpuestos (aproximacion a Perlin 1D)."""
    v  = np.sin(t * 1.000 + seed) * 1.000
    v += np.sin(t * 2.137 + seed * 1.73) * 0.500
    v += np.sin(t * 4.371 + seed * 3.14) * 0.250
    v += np.sin(t * 9.113 + seed * 5.29) * 0.125
    return v / 1.875


class Brazo:
    """Un brazo: 3 servos con su zona segura, en angulos LOGICOS."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.numero = cfg["brazo"]
        self.servos = cfg["servos"][:SERVOS_POR_BRAZO]
        self.home = [float(s["home"]) for s in self.servos]
        self.pos = list(self.home)
        self.target = list(self.home)
        self.semilla = self.numero * 7.13
        self.viendo_rostro = False
        self.ultimo_rostro = 0.0

    def limites(self, i):
        return self.servos[i]["min"], self.servos[i]["max"]

    def recortar(self, i, v):
        lo, hi = self.limites(i)
        return max(lo, min(hi, v))

    def seguir(self, err_x, err_y, ancho, alto):
        """Centra el rostro moviendo base (yaw) y codo (tilt)."""
        self.viendo_rostro = True
        self.ultimo_rostro = time.time()
        self.target[0] = self.recortar(
            0, self.target[0] + float(np.clip(err_x / (ancho / 2) * 5, -5, 5)))
        self.target[2] = self.recortar(
            2, self.target[2] - float(np.clip(err_y / (alto / 2) * 5, -5, 5)))
        # el hombro acompaña suavemente hacia el frente
        self.target[1] = self.recortar(1, self.home[1] + 12)

    def buscar(self, ahora):
        """Vagabundeo suave dentro de la zona segura. Para brazos ciegos."""
        self.viendo_rostro = False
        for i in range(SERVOS_POR_BRAZO):
            lo, hi = self.limites(i)
            margen = min(self.home[i] - lo, hi - self.home[i]) * 0.55
            n = _snoise(ahora * 0.45 + i * 1.7, seed=self.semilla + i)
            self.target[i] = self.recortar(i, self.home[i] + n * margen)

    def interpolar(self, factor):
        for i in range(SERVOS_POR_BRAZO):
            self.pos[i] += (self.target[i] - self.pos[i]) * factor
            self.pos[i] = self.recortar(i, self.pos[i])

    def angulos_para_arduino(self):
        """Angulos LOGICOS ya recortados. El firmware vuelve a recortar."""
        return [int(round(self.pos[i])) for i in range(SERVOS_POR_BRAZO)]


class Enlace:
    """Canal serial con el Arduino."""

    def __init__(self, puerto, baud=115200, activo=True):
        self.activo = activo
        self.ser = None
        self.ultima_trama = ""
        if not activo:
            print("  [sin-arduino] no se abre el puerto serial")
            return
        try:
            import serial
        except ImportError:
            sys.exit("Falta pyserial.  pip install pyserial")
        self.ser = serial.Serial(puerto, baud, timeout=0.01)
        time.sleep(2.0)
        self.ser.reset_input_buffer()
        print(f"  Arduino conectado en {puerto}")

    def enviar(self, brazos):
        """Manda una trama $a0,...,aN,1 en orden de servo global."""
        valores = []
        for br in brazos:
            valores.extend(br.angulos_para_arduino())
        trama = "$" + ",".join(str(v) for v in valores) + ",1\n"
        self.ultima_trama = trama.strip()
        if self.ser is not None:
            self.ser.write(trama.encode())

    def cerrar(self):
        if self.ser is not None:
            self.ser.close()


# ===============================================================
# Base de datos de rostros
# ===============================================================
def cargar_base():
    if not os.path.exists(DB_FILE):
        print(f"  ! No existe {DB_FILE}. El sistema corre sin cotejo.")
        return [], None
    with open(DB_FILE, "rb") as f:
        base = pickle.load(f)
    print(f"  Base de datos: {len(base)} rostros")
    embs = np.array([e["embedding"] for e in base]) if base else None
    return base, embs


# ===============================================================
# Dibujo
# ===============================================================
def _bracket(img, x, y, w, h, color=_GREEN, thick=2, L=20):
    for pts in [
        [(x, y + L), (x, y), (x + L, y)],
        [(x + w - L, y), (x + w, y), (x + w, y + L)],
        [(x + w, y + h - L), (x + w, y + h), (x + w - L, y + h)],
        [(x + L, y + h), (x, y + h), (x, y + h - L)],
    ]:
        for i in range(len(pts) - 1):
            cv2.line(img, pts[i], pts[i + 1], color, thick)


def _sc(pct):
    if pct > 60:
        return _GREEN
    if pct > 40:
        return _YELLOW
    return (80, 80, 80)


def mosaico(gestor, estados, ancho_celda=300, alto_celda=400):
    """Fila con las camaras abiertas, etiquetadas por brazo."""
    n = max(1, gestor.max_abiertas)
    lienzo = np.full((alto_celda + 26, ancho_celda * n, 3), _BG, dtype=np.uint8)
    abiertas = gestor.abiertas

    for k in range(n):
        x0 = k * ancho_celda
        if k < len(abiertas):
            c = abiertas[k]
            f = c.leer()
            est = estados.get(c.brazo, {})
            if f is not None:
                f = cv2.resize(f, (ancho_celda, alto_celda))
                lienzo[26:26 + alto_celda, x0:x0 + ancho_celda] = f
                bbox = est.get("bbox")
                if bbox is not None:
                    fx = ancho_celda / est["ancho"]
                    fy = alto_celda / est["alto"]
                    bx, by = int(bbox[0] * fx), int(bbox[1] * fy) + 26
                    bw = int((bbox[2] - bbox[0]) * fx)
                    bh = int((bbox[3] - bbox[1]) * fy)
                    _bracket(lienzo, bx, by, bw, bh, _GREEN, 2, 12)
            color = _GREEN if est.get("rostro") else _DIM
            cv2.putText(lienzo, f"BRAZO {c.brazo}  cam{c.indice}",
                        (x0 + 6, 17), _FONT, 0.4, color, 1)
            cv2.putText(lienzo, f"{c.fps:.0f}fps",
                        (x0 + ancho_celda - 46, 17), _FONT, 0.34, _DIM, 1)
            if est.get("rostro"):
                cv2.circle(lienzo, (x0 + ancho_celda - 8, 12), 4, _GREEN, -1)
        else:
            cv2.putText(lienzo, "-- sin senal --",
                        (x0 + 60, 26 + alto_celda // 2), _FONT, 0.4, (40, 40, 40), 1)
        cv2.line(lienzo, (x0, 0), (x0, alto_celda + 26), (30, 30, 30), 1)

    return lienzo


def panel_coincidencias(base, indices, sims, cursor, cerradas_txt):
    _CW, _PH, _LH, _GAP = 143, 165, 30, 4
    canvas = np.full((494, 600, 3), _BG, dtype=np.uint8)

    cv2.putText(canvas, "similitud facial / tiempo real", (12, 16), _FONT, 0.28, _DIM, 1)
    cv2.putText(canvas, f"COINCIDENCIAS{cursor}", (12, 46), _FONT, 0.68, _WHITE, 2)
    cv2.putText(canvas, "BASE DE DATOS", (390, 16), _FONT, 0.26, _DIM, 1)
    cv2.putText(canvas, f"{len(base):,}" if base else "...", (390, 42), _FONT, 0.6, _WHITE, 2)
    cv2.putText(canvas, "PERSONAS INDEXADAS", (390, 55), _FONT, 0.24, _DIM, 1)
    cv2.line(canvas, (0, 62), (600, 62), (35, 35, 35), 1)

    if indices is not None and base and sims is not None:
        for i, idx in enumerate(indices[:8]):
            m = base[idx]
            row, col = i // 4, i % 4
            x0 = _GAP + col * (_CW + _GAP)
            y0 = 66 + row * (_PH + _LH + _GAP)

            ruta = m["original_path"]
            if not os.path.exists(ruta):
                ruta = os.path.join(FCAES_DIR, m.get("year", ""),
                                    "fotos_recortadas", os.path.basename(ruta))
            img = cv2.imread(ruta)
            if img is not None:
                canvas[y0:y0 + _PH, x0:x0 + _CW] = cv2.resize(img, (_CW, _PH))
                _bracket(canvas, x0, y0, _CW, _PH, _GREEN, 1, 9)
            else:
                cv2.rectangle(canvas, (x0, y0), (x0 + _CW, y0 + _PH), (18, 18, 18), -1)
                cv2.putText(canvas, "SIN FOTO", (x0 + 20, y0 + 82), _FONT, 0.35, (45, 45, 45), 1)

            pct = int(float(sims[idx]) * 100)
            sc = _sc(pct)
            cv2.putText(canvas, f"#{i+1:02d}", (x0 + 2, y0 + 11), _FONT, 0.28, (60, 60, 60), 1)
            cv2.putText(canvas, f"{pct}%", (x0 + _CW - 34, y0 + 11), _FONT, 0.3, sc, 1)

            ly = y0 + _PH
            cv2.rectangle(canvas, (x0, ly), (x0 + _CW, ly + _LH), (14, 14, 14), -1)
            cv2.putText(canvas, m["name"][:18], (x0 + 2, ly + 12), _FONT, 0.27, _WHITE, 1)
            cv2.putText(canvas, m.get("year", ""), (x0 + 2, ly + 24), _FONT, 0.23, _DIM, 1)
            bw = int((_CW - 4) * pct / 100)
            cv2.rectangle(canvas, (x0 + 2, ly + 27), (x0 + 2 + bw, ly + 29), sc, -1)
            cv2.rectangle(canvas, (x0 + 2, ly + 27), (x0 + _CW - 2, ly + 29), (28, 28, 28), 1)
    else:
        cv2.putText(canvas, "POSICIONATE FRENTE A UNA CAMARA...",
                    (30, 290), _FONT, 0.38, (45, 45, 45), 1)

    cv2.line(canvas, (0, 472), (600, 472), (28, 28, 28), 1)
    cv2.putText(canvas, "MIL OJOS - v4", (12, 488), _FONT, 0.26, (50, 50, 50), 1)
    cv2.putText(canvas, cerradas_txt, (150, 488), _FONT, 0.26, (50, 50, 50), 1)
    cv2.putText(canvas, time.strftime("%H:%M:%S"), (498, 488), _FONT, 0.26, (50, 50, 50), 1)
    return canvas


# ===============================================================
def cargar_mapeo(brazos_pedidos=None):
    if not os.path.exists(RUTA_CAMARAS):
        sys.exit(f"No existe {RUTA_CAMARAS}.\n"
                 f"Corre primero:  python emparejar_camaras.py --puerto COM6")
    with open(RUTA_CAMARAS, "r", encoding="utf-8") as f:
        datos = json.load(f)
    pares = [(c["brazo"], c["indice_cv2"]) for c in datos.get("camaras", [])]
    if brazos_pedidos:
        pares = [p for p in pares if p[0] in brazos_pedidos]
    if not pares:
        sys.exit("El mapeo no tiene camaras. Vuelve a correr emparejar_camaras.py")
    print(f"  Mapeo camara-brazo: " +
          ", ".join(f"brazo {b}<-cam {i}" for b, i in pares))
    print(f"  (generado {datos.get('generado', '?')})")
    return pares


def main():
    ap = argparse.ArgumentParser(description="MIL OJOS - sistema completo")
    ap.add_argument("--puerto", default="COM6")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--abiertas", type=int, default=3,
                    help="cuantas camaras abiertas a la vez (limite del bus USB)")
    ap.add_argument("--rotacion", type=float, default=SEG_ROTACION)
    ap.add_argument("--brazos", help="limitar a estos brazos, ej 0,1,2,3")
    ap.add_argument("--sin-arduino", action="store_true")
    ap.add_argument("--umbral", type=float, default=0.0,
                    help="similitud minima para mostrar coincidencias")
    args = ap.parse_args()

    print("\n" + "=" * 62)
    print("  MIL OJOS - SISTEMA")
    print("=" * 62)

    pedidos = None
    if args.brazos:
        pedidos = [int(x) for x in args.brazos.split(",") if x.strip().isdigit()]
    mapeo = cargar_mapeo(pedidos)
    numeros = sorted({b for b, _ in mapeo})

    brazos = {b: Brazo(cargar_config(b)) for b in numeros}
    print(f"  Brazos activos: {numeros}")

    print("\n  Cargando InsightFace...")
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=DET_SIZE)

    base, embs = cargar_base()
    os.makedirs(CAPTURAS_DIR, exist_ok=True)

    enlace = Enlace(args.puerto, args.baud, activo=not args.sin_arduino)
    gestor = GestorCamaras(mapeo, args.abiertas, args.rotacion)
    print(f"  Ventana de {gestor.max_abiertas} camaras abiertas de {len(mapeo)}\n")

    estados = {b: {} for b in numeros}
    historial = []
    indices_mostrados = None
    sims_cache = None
    ultima_foto = 0.0
    turno_deteccion = 0
    cursor_on = True
    ultimo_parpadeo = time.time()

    try:
        while True:
            ahora = time.time()

            cambio = gestor.paso()
            if cambio:
                print(f"  [rotacion] cierra brazo {cambio[0]}, abre brazo {cambio[1]}")

            abiertas = gestor.abiertas

            # --- deteccion: una camara por vuelta, para no ahogar la CPU ---
            if abiertas:
                cam = abiertas[turno_deteccion % len(abiertas)]
                turno_deteccion += 1
                frame = cam.leer()
                if frame is not None:
                    h, w = frame.shape[:2]
                    caras = app.get(frame)
                    est = estados.setdefault(cam.brazo, {})
                    est["ancho"], est["alto"] = w, h

                    if caras:
                        cam.ultimo_rostro = ahora
                        principal = max(caras, key=lambda x: (x.bbox[2] - x.bbox[0]) *
                                                             (x.bbox[3] - x.bbox[1]))
                        bbox = principal.bbox.astype(int)
                        est["bbox"] = bbox
                        est["rostro"] = True

                        cx, cy = w // 2, h // 2
                        tx = (bbox[0] + bbox[2]) // 2
                        ty = (bbox[1] + bbox[3]) // 2
                        brazos[cam.brazo].seguir(cx - tx, cy - ty, w, h)

                        # --- cotejo contra la base ---
                        if embs is not None and len(embs):
                            sims = np.dot(embs, principal.normed_embedding)
                            historial.append(int(np.argmax(sims)))
                            if len(historial) > MAX_HISTORY:
                                historial.pop(0)
                            top, cuenta = Counter(historial).most_common(1)[0]
                            if (indices_mostrados is None or
                                    (top != indices_mostrados[0] and cuenta >= 8)):
                                indices_mostrados = np.argsort(sims)[-8:][::-1]
                            sims_cache = sims

                        if ahora - ultima_foto > SEG_CAPTURA:
                            ultima_foto = ahora
                            ts = time.strftime("%Y%m%d_%H%M%S")
                            cv2.imwrite(os.path.join(
                                CAPTURAS_DIR, f"brazo{cam.brazo}_{ts}.jpg"), frame)
                    else:
                        est["rostro"] = False
                        est["bbox"] = None

            # --- brazos sin camara abierta o sin rostro: a buscar ---
            abiertos_num = {c.brazo for c in abiertas}
            for n, br in brazos.items():
                sin_rostro_reciente = ahora - br.ultimo_rostro > 1.5
                if n not in abiertos_num or sin_rostro_reciente:
                    br.buscar(ahora)
                br.interpolar(0.22 if br.viendo_rostro else 0.10)

            # --- mandar al Arduino ---
            enlace.enviar([brazos[n] for n in numeros])

            # --- interfaz ---
            if ahora - ultimo_parpadeo > 0.6:
                cursor_on = not cursor_on
                ultimo_parpadeo = ahora

            cerradas_txt = "espera: " + ",".join(
                f"b{c.brazo}" for c in gestor.cerradas) if gestor.cerradas else ""

            cv2.imshow("MIL OJOS - Camaras", mosaico(gestor, estados))
            cv2.imshow("MIL OJOS - Coincidencias",
                       panel_coincidencias(base, indices_mostrados, sims_cache,
                                           "_" if cursor_on else " ", cerradas_txt))

            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break

    except KeyboardInterrupt:
        pass
    finally:
        print("\n  Cerrando...")
        gestor.cerrar_todo()
        cv2.destroyAllWindows()
        enlace.cerrar()
        print("  Listo.\n")


if __name__ == "__main__":
    main()
