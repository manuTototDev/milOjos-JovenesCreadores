#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emparejar_camaras.py - MilOjos
===============================================================
Averigua QUE CAMARA pertenece a QUE BRAZO sacudiendo cada brazo y
viendo cual imagen se mueve.

Las 8 camaras son identicas (VID 2CE3 / PID C670, sin numero de serie),
asi que el sistema operativo no las distingue. Pero la camara va montada
EN el brazo: si el brazo se sacude, TODO su encuadre se desplaza, mientras
que una camara ajena solo ve un objeto pequeño moverse en una esquina.
Esa diferencia es la que medimos.

  medida = desplazamiento global de la imagen en pixeles (correlacion de fase)
           camara montada en el brazo -> se traslada todo el encuadre (~12px)
           camara espectadora         -> la escena no se mueve (<1px)

La decision es RELATIVA: se compara cada camara consigo misma entre brazos,
asi no dependemos del contraste ni de la iluminacion de cada escena.

OJO: el indice de OpenCV NO es estable entre arranques. camaras.json es
un artefacto de SESION: regeneralo cuando reconectes cables o reinicies.

Uso:
    python emparejar_camaras.py --puerto COM6
    python emparejar_camaras.py --puerto COM6 --brazos 0,1,2,3
    python emparejar_camaras.py --puerto COM6 --max-indice 6
    python emparejar_camaras.py --verificar          # comprueba el mapeo guardado
===============================================================
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from calibrar_brazos import (
    Controlador, DIR_CONFIG, NUM_BRAZOS, SERVOS_POR_BRAZO,
    angulo_fisico, canales_de_brazo, cargar_config, leer_linea,
)

RUTA_CAMARAS = os.path.join(DIR_CONFIG, "camaras.json")

# --- parametros de medicion ---
# QUE MEDIMOS: el desplazamiento GLOBAL de la imagen, via correlacion de fase.
# Si la camara va montada en el brazo, al sacudirlo la escena entera se traslada
# varios pixeles. Si la camara solo MIRA el brazo desde fuera, la escena se queda
# donde esta y unicamente cambia una region pequeña.
#
# Contar "pixeles que cambiaron" no sirve: frente a una pared lisa, trasladar la
# imagen no cambia casi ningun pixel, mientras que un objeto claro cruzando el
# encuadre cambia muchos. Media lo contrario de lo que queriamos.
#
# Ademas el criterio es RELATIVO: cada camara se compara consigo misma entre
# brazos, asi no dependemos de la iluminacion ni del contraste de cada escena.
ANCHO_PRUEBA, ALTO_PRUEBA = 320, 240   # bajo, para no saturar el bus USB
PISO_DESPLAZAMIENTO = 2.0   # px: por debajo de esto la imagen no se movio
FACTOR_CLARIDAD = 2.5       # el ganador debe superar al segundo por este factor
TEXTURA_MINIMA = 1.0        # varianza del laplaciano; menos = escena sin rasgos
                            # (solo se usa para explicar un fallo, no como filtro)

# La correlacion de fase es fiable mientras el desplazamiento sea CHICO frente
# al tamaño del cuadro: los fotogramas tienen que traslaparse. Una sacudida de
# 18 grados mueve la imagen ~100 px de 320 y el pico aterriza sobre ruido,
# devolviendo cifras enormes con confianza cero. Con 6 grados el corrimiento
# ronda 30 px y la medicion es limpia.
AMPLITUD = 6                # grados de sacudida
PICO_MINIMO = 0.25          # confianza minima del pico; abajo la cifra no vale
MAX_DESPLAZAMIENTO = 0.35   # fraccion del ancho: mas que esto no es creible
REPETICIONES = 3            # se sacude varias veces y se toma la mediana
DUR_CAPTURA = 0.8           # segundos capturando durante el movimiento
SEG_ASENTAR = 0.8           # espera antes de tomar la referencia en reposo


# ---------------------------------------------------------------
# Camara
# ---------------------------------------------------------------
class Camara:
    """Una camara abierta a baja resolucion. Se abre de una en una."""

    def __init__(self, indice):
        self.indice = indice
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(indice, backend)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO_PRUEBA)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO_PRUEBA)
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass

    def abierta(self):
        return self.cap is not None and self.cap.isOpened()

    def frame(self):
        """Devuelve un frame en gris, suavizado. None si falla."""
        if not self.abierta():
            return None
        ok, img = self.cap.read()
        if not ok or img is None:
            return None
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gris, (5, 5), 0)

    def descartar(self, n=5):
        """Tira frames viejos del buffer."""
        for _ in range(n):
            self.cap.read()

    def cerrar(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def desplazamiento(a, b, ventana=None):
    """Cuantos pixeles se traslado la imagen entre a y b (correlacion de fase).

    Devuelve (magnitud_px, respuesta). La respuesta 0..1 indica que tan nitido
    fue el pico de correlacion: valores altos = traslacion limpia y confiable.
    """
    if a is None or b is None or a.shape != b.shape:
        return 0.0, 0.0
    fa = np.float32(a)
    fb = np.float32(b)
    if ventana is None:
        ventana = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), respuesta = cv2.phaseCorrelate(fa, fb, ventana)
    return float(np.hypot(dx, dy)), float(respuesta)


def textura(frame):
    """Cuanto detalle tiene la escena. Una pared lisa da casi cero."""
    if frame is None:
        return 0.0
    return float(cv2.Laplacian(frame, cv2.CV_64F).var())


def detectar_indices(maximo=10):
    """Prueba indices 0..maximo-1 y devuelve los que entregan imagen."""
    print(f"  Buscando camaras en los indices 0..{maximo - 1} ...")
    encontrados = []
    for i in range(maximo):
        cam = Camara(i)
        if cam.abierta():
            cam.descartar(3)
            if cam.frame() is not None:
                encontrados.append(i)
                print(f"    indice {i}: responde")
        cam.cerrar()
        time.sleep(0.15)
    return encontrados


# ---------------------------------------------------------------
# Sacudida
# ---------------------------------------------------------------
def servo_para_sacudir(cfg):
    """Elige el servo del brazo que mas desplaza la camara (la base)."""
    for s in cfg["servos"]:
        if s["articulacion"] != "SIN_CONECTAR":
            return s
    return None


def _una_sacudida(ctrl, cam, cfg, servo, centro, destino, ventana, limite_px):
    """Una ida: devuelve (desplazamiento_valido, pico, quieto) o None si no sirve."""
    placa = cfg["placa_index"]
    canal = servo["canal"]

    ctrl.mover(placa, canal, angulo_fisico(servo, centro))
    time.sleep(SEG_ASENTAR)          # que deje de vibrar antes de la referencia
    cam.descartar(5)

    base = cam.frame()
    if base is None:
        return None

    # deriva con todo quieto: si esto ya es grande, la escena no esta estable
    time.sleep(0.2)
    quieto, _ = desplazamiento(base, cam.frame(), ventana)

    ctrl.enviar(f"M {placa} {canal} {angulo_fisico(servo, destino)}",
                espera_respuesta=False)
    medidas = []
    t0 = time.time()
    while time.time() - t0 < DUR_CAPTURA:
        f = cam.frame()
        if f is not None:
            medidas.append(desplazamiento(base, f, ventana))
    ctrl.esperar_respuesta()

    if not medidas:
        return None

    # Solo valen las mediciones con pico nitido y corrimiento creible.
    # Un pico de 0.01 con 199px es el algoritmo perdido en el ruido.
    validas = [(px, r) for px, r in medidas
               if r >= PICO_MINIMO and px <= limite_px]
    if not validas:
        mejor_r = max(m[1] for m in medidas)
        mayor_px = max(m[0] for m in medidas)
        return (0.0, mejor_r, quieto, f"descartada (pico max {mejor_r:.2f}, "
                                      f"{mayor_px:.0f}px)")

    px, resp = max(validas, key=lambda m: m[0])
    return (max(0.0, px - quieto), resp, quieto, None)


def medir_sacudida(ctrl, cam, cfg, servo):
    """Sacude el brazo varias veces y devuelve la mediana de lo confiable."""
    placa = cfg["placa_index"]
    canal = servo["canal"]
    lo, hi = servo["min"], servo["max"]
    centro = max(lo, min(hi, servo["home"]))
    limite_px = ANCHO_PRUEBA * MAX_DESPLAZAMIENTO

    # dos destinos, uno a cada lado si cabe, para sacudir en ambos sentidos
    destinos = []
    if hi - centro >= AMPLITUD:
        destinos.append(min(hi, centro + AMPLITUD))
    if centro - lo >= AMPLITUD:
        destinos.append(max(lo, centro - AMPLITUD))
    if not destinos:
        margen = max(hi - centro, centro - lo)
        if margen < 3:
            return 0.0, "zona segura demasiado estrecha para sacudir"
        destinos.append(centro + margen if hi - centro > centro - lo
                        else centro - margen)

    base_frame = cam.frame()
    if base_frame is None:
        return 0.0, "sin imagen"
    ventana = cv2.createHanningWindow(
        (base_frame.shape[1], base_frame.shape[0]), cv2.CV_32F)

    valores, picos, quietos, descartes = [], [], [], 0
    for rep in range(REPETICIONES):
        destino = destinos[rep % len(destinos)]
        r = _una_sacudida(ctrl, cam, cfg, servo, centro, destino,
                          ventana, limite_px)
        if r is None:
            descartes += 1
            continue
        px, pico, quieto, nota_mala = r
        quietos.append(quieto)
        if nota_mala:
            descartes += 1
            picos.append(pico)
            continue
        valores.append(px)
        picos.append(pico)

    ctrl.mover(placa, canal, angulo_fisico(servo, centro))

    q = float(np.median(quietos)) if quietos else 0.0
    p = float(np.median(picos)) if picos else 0.0

    if len(valores) == 0:
        return 0.0, (f"sin medicion confiable ({descartes}/{REPETICIONES} "
                     f"descartadas, pico max {p:.2f})")
    if len(valores) < 2 and REPETICIONES >= 3:
        # una sola lectura buena de tres: sospechoso, se reporta pero se penaliza
        return valores[0] * 0.5, (f"{valores[0]:.1f}px pero solo 1/{REPETICIONES} "
                                  f"confiable  pico={p:.2f}")

    med = float(np.median(valores))
    return med, (f"{med:.1f}px  pico={p:.2f}  quieto={q:.1f}px  "
                 f"({len(valores)}/{REPETICIONES} buenas)")


# ---------------------------------------------------------------
# Emparejamiento
# ---------------------------------------------------------------
def emparejar(ctrl, indices, brazos):
    """Devuelve (asignaciones, camaras_sin_brazo, brazos_sin_camara)."""
    configs = {b: cargar_config(b) for b in brazos}
    servos = {b: servo_para_sacudir(configs[b]) for b in brazos}

    for b, s in servos.items():
        if s is None:
            print(f"  ! brazo {b} no tiene ningun servo utilizable, se omite")
    brazos = [b for b in brazos if servos[b] is not None]

    asignado = {}        # brazo -> dict con indice y score
    usados = set()       # indices ya asignados
    sin_brazo = []

    for idx in indices:
        print("\n" + "-" * 62)
        print(f"  CAMARA indice {idx}")
        print("-" * 62)
        cam = Camara(idx)
        if not cam.abierta():
            print("    no abre, se omite")
            sin_brazo.append(idx)
            continue
        cam.descartar(6)
        tex = textura(cam.frame())

        scores = {}
        for b in brazos:
            if b in asignado:
                continue
            score, nota = medir_sacudida(ctrl, cam, configs[b], servos[b])
            scores[b] = score
            print(f"        brazo {b}: {nota}")

        cam.cerrar()
        time.sleep(0.2)

        if not scores:
            sin_brazo.append(idx)
            continue

        orden = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        mejor_b, mejor_s = orden[0]
        segundo_s = orden[1][1] if len(orden) > 1 else 0.0
        # cuantas veces mas se movio el ganador que el resto
        ratio = mejor_s / segundo_s if segundo_s > 1e-6 else float("inf")

        if mejor_s < PISO_DESPLAZAMIENTO:
            if tex < TEXTURA_MINIMA:
                # no podemos concluir nada: la escena no tiene rasgos que seguir
                print(f"    -> NO CONCLUYENTE: la escena casi no tiene textura "
                      f"(={tex:.1f}). Apunta esta camara a algo con detalle "
                      f"(un poster, una repisa) y vuelve a correr el emparejamiento.")
            else:
                print(f"    -> la imagen nunca se traslado (max {mejor_s:.1f}px); "
                      f"no esta montada en un brazo (webcam integrada / C920?)")
            sin_brazo.append(idx)
        elif ratio < FACTOR_CLARIDAD:
            print(f"    -> AMBIGUO: brazo {mejor_b} ({mejor_s:.1f}px) vs "
                  f"{orden[1][0]} ({segundo_s:.1f}px), solo {ratio:.1f}x de diferencia")
            resp = leer_linea("       ¿A que brazo pertenece? (numero, o Enter para omitir): ").strip()
            if resp.isdigit() and int(resp) in brazos and int(resp) not in asignado:
                b = int(resp)
                # mismas claves que la rama automatica: antes usaba "score" aqui
                # y "desplazamiento_px" alla, y el resumen reventaba
                asignado[b] = {
                    "indice_cv2": idx,
                    "desplazamiento_px": round(scores.get(b, 0.0), 2),
                    "ratio": None,
                    "confianza": "manual",
                }
                usados.add(idx)
            else:
                sin_brazo.append(idx)
        else:
            r = "inf" if ratio == float("inf") else f"{ratio:.1f}"
            print(f"    -> BRAZO {mejor_b}  ({mejor_s:.1f}px, "
                  f"{r}x sobre el segundo)")
            asignado[mejor_b] = {
                "indice_cv2": idx,
                "desplazamiento_px": round(mejor_s, 2),
                "ratio": None if ratio == float("inf") else round(ratio, 2),
                "confianza": "alta",
            }
            usados.add(idx)

    sin_camara = [b for b in brazos if b not in asignado]
    return asignado, sin_brazo, sin_camara


def guardar(asignado, sin_brazo, sin_camara, previo=None):
    os.makedirs(DIR_CONFIG, exist_ok=True)
    if previo:
        # conservamos lo que ya estaba resuelto y añadimos lo nuevo
        for c in previo.get("camaras", []):
            asignado.setdefault(c["brazo"], {k: v for k, v in c.items()
                                            if k != "brazo"})
        usados = {d["indice_cv2"] for d in asignado.values()}
        sin_brazo = sorted(set(sin_brazo) - usados)
        sin_camara = sorted(set(sin_camara) - set(asignado))
    datos = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "aviso": ("El indice de OpenCV NO es estable entre arranques. "
                  "Regenera este archivo al reconectar camaras o reiniciar."),
        "resolucion_prueba": [ANCHO_PRUEBA, ALTO_PRUEBA],
        "camaras": [
            {"brazo": b, **d} for b, d in sorted(asignado.items())
        ],
        "camaras_sin_brazo": sin_brazo,
        "brazos_sin_camara": sin_camara,
    }
    with open(RUTA_CAMARAS, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    print(f"\n  Guardado -> {RUTA_CAMARAS}")
    return datos


def cargar_mapeo():
    if not os.path.exists(RUTA_CAMARAS):
        return None
    with open(RUTA_CAMARAS, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------
# Verificacion rapida del mapeo guardado
# ---------------------------------------------------------------
def verificar(ctrl, mapeo):
    """Comprueba una sola pareja: si falla, todo el mapeo es sospechoso."""
    if not mapeo or not mapeo.get("camaras"):
        print("  No hay mapeo guardado.")
        return False

    entrada = mapeo["camaras"][0]
    b, idx = entrada["brazo"], entrada["indice_cv2"]
    print(f"  Verificando: brazo {b} deberia mover la camara {idx} ...")

    cfg = cargar_config(b)
    servo = servo_para_sacudir(cfg)
    if servo is None:
        print("  El brazo no tiene servos utilizables.")
        return False

    cam = Camara(idx)
    if not cam.abierta():
        print(f"  La camara {idx} ya no existe. El mapeo caduco.")
        return False
    cam.descartar(6)
    score, nota = medir_sacudida(ctrl, cam, cfg, servo)
    cam.cerrar()

    # en verificacion solo tenemos una pareja, asi que comparamos contra el
    # score que se registro cuando se hizo el emparejamiento
    referencia = entrada.get("desplazamiento_px", PISO_DESPLAZAMIENTO)
    ok = score >= max(PISO_DESPLAZAMIENTO, referencia * 0.4)
    print(f"  {nota} (referencia {referencia:.1f}px) "
          f"-> {'OK' if ok else 'NO CUADRA'}")
    return ok


# ---------------------------------------------------------------
def main():
    global AMPLITUD, REPETICIONES

    ap = argparse.ArgumentParser(description="Empareja camaras con brazos por sacudida")
    ap.add_argument("--puerto", help="puerto serial del Arduino, ej COM6")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--brazos", help="lista de brazos a probar, ej 0,1,2,3")
    ap.add_argument("--max-indice", type=int, default=10,
                    help="hasta que indice de camara buscar")
    ap.add_argument("--indices", help="usa estos indices en vez de detectarlos, ej 0,1,2,4")
    ap.add_argument("--amplitud", type=int, default=AMPLITUD,
                    help="grados de sacudida (chico = medicion mas limpia)")
    ap.add_argument("--repeticiones", type=int, default=REPETICIONES)
    ap.add_argument("--completar", action="store_true",
                    help="conserva el mapeo guardado y solo busca los que faltan")
    ap.add_argument("--verificar", action="store_true",
                    help="solo comprueba el mapeo guardado")
    ap.add_argument("--simular", action="store_true")
    args = ap.parse_args()

    AMPLITUD = args.amplitud
    REPETICIONES = args.repeticiones

    print("\n" + "=" * 62)
    print("  MILOJOS - EMPAREJAR CAMARAS CON BRAZOS")
    print("=" * 62)
    print(f"  sacudida {AMPLITUD} grados x {REPETICIONES} repeticiones, "
          f"pico minimo {PICO_MINIMO}")

    # brazos a probar: por defecto los que tengan JSON
    if args.brazos:
        brazos = [int(x) for x in args.brazos.split(",") if x.strip().isdigit()]
    else:
        brazos = sorted(
            int(os.path.basename(p).split("_")[1].split(".")[0])
            for p in glob.glob(os.path.join(DIR_CONFIG, "brazo_*.json"))
        )
        if not brazos:
            brazos = list(range(NUM_BRAZOS))
    print(f"  Brazos a probar: {brazos}")

    ctrl = Controlador(args.puerto, args.baud, args.simular)

    try:
        if args.verificar:
            ok = verificar(ctrl, cargar_mapeo())
            sys.exit(0 if ok else 1)

        if args.indices:
            indices = [int(x) for x in args.indices.split(",") if x.strip().isdigit()]
            print(f"  Indices dados: {indices}")
        else:
            indices = detectar_indices(args.max_indice)

        if not indices:
            print("\n  No se encontro ninguna camara.")
            return

        previo = None
        if args.completar:
            previo = cargar_mapeo()
            if previo and previo.get("camaras"):
                ya = {c["brazo"] for c in previo["camaras"]}
                ocupados = {c["indice_cv2"] for c in previo["camaras"]}
                print(f"\n  Conservando lo ya resuelto: " + ", ".join(
                    f"brazo {c['brazo']}<-cam {c['indice_cv2']}"
                    for c in previo["camaras"]))
                brazos = [b for b in brazos if b not in ya]
                indices = [i for i in indices if i not in ocupados]
                if not brazos:
                    print("  No falta ningun brazo. Nada que hacer.")
                    return
                print(f"  Faltan los brazos {brazos} entre las camaras {indices}")
            else:
                print("\n  No hay mapeo previo; se hace completo.")
                previo = None

        print(f"\n  Camaras a probar: {indices}")
        print("  Empieza el emparejamiento. Cada brazo se sacudira dentro de su zona segura.")

        asignado, sin_brazo, sin_camara = emparejar(ctrl, indices, brazos)

        print("\n" + "=" * 62)
        print("  RESULTADO")
        print("=" * 62)
        for b, d in sorted(asignado.items()):
            print(f"    brazo {b}  <-  camara indice {d['indice_cv2']}"
                  f"   ({d['desplazamiento_px']:.1f}px, {d['confianza']})")
        if sin_brazo:
            print(f"    camaras que no son de ningun brazo: {sin_brazo}")
        if sin_camara:
            print(f"    brazos sin camara encontrada: {sin_camara}")

        guardar(asignado, sin_brazo, sin_camara, previo)
    finally:
        ctrl.cerrar(liberar=False)


if __name__ == "__main__":
    main()
