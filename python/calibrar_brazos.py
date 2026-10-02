#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrar_brazos.py - MilOjos
===============================================================
Verifica el mapeo canal->servo y define zonas seguras, brazo por brazo.
Genera un JSON por brazo en Dev/config/brazo_N.json

Hardware asumido:
    3x PCA9685 -> 27 canales -> 9 brazos de 3 servos (base, hombro, codo)
    brazo 0..2 -> placa 0 (0x40), canales (brazo%3)*3 .. +2
    brazo 3..5 -> placa 1 (0x41), canales (brazo%3)*3 .. +2
    brazo 6..8 -> placa 2 (0x42), canales (brazo%3)*3 .. +2

Requiere el sketch arduino/calibrador/calibrador.ino cargado.

Uso:
    python calibrar_brazos.py                 # autodetecta puerto
    python calibrar_brazos.py --puerto COM5
    python calibrar_brazos.py --brazo 2       # entra directo a ese brazo
    python calibrar_brazos.py --simular       # sin hardware, para probar el flujo
===============================================================
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------
# Constantes de proyecto
# ---------------------------------------------------------------
NUM_BRAZOS = 9
SERVOS_POR_BRAZO = 3
DIRECCIONES = ["0x40", "0x41", "0x42"]

# Nombres por defecto de las articulaciones dentro de un brazo.
# El slot 0 es el primer servo del brazo, el 2 el ultimo.
ARTICULACIONES_DEF = ["base", "hombro", "codo"]

# Convencion de sentido por slot: que significa un angulo BAJO y uno ALTO.
# Todos los brazos deben obedecer esto; si un servo esta montado al reves,
# se marca "invertido" y el software le da la vuelta al angulo.
SENTIDOS = {
    0: ("izquierda", "derecha"),   # base:   0 = izquierda, 160 = derecha
    1: ("atras", "adelante"),      # hombro: 0 = atras,     160 = adelante
    2: ("atras", "adelante"),      # codo:   0 = atras,     160 = adelante
}


def convencion(slot):
    return SENTIDOS.get(slot, ("menos", "mas"))


def angulo_fisico(servo, ang):
    """Traduce un angulo LOGICO (el de la convencion) al que se le manda al servo.

    Si el servo esta montado al reves, invertimos aqui y en un solo lugar. Asi
    todo lo demas -- limites, HOME, el sketch de Arduino -- trabaja siempre en
    la misma convencion sin importar como quedo atornillado cada servo.
    """
    return 180 - ang if servo.get("invertido") else ang

# Punto de partida seguro al empezar a mover un servo desconocido.
ANGULO_ARRANQUE = 90

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CONFIG = os.path.join(RAIZ, "config")


# ---------------------------------------------------------------
# Teclado (Windows / Unix)
# ---------------------------------------------------------------
if os.name == "nt":
    import msvcrt

    def leer_tecla():
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            code = msvcrt.getch()
            return {b"H": "ARR", b"P": "ABA", b"K": "IZQ", b"M": "DER"}.get(code, "?")
        if ch == b"\r":
            return "ENTER"
        if ch == b"\x1b":
            return "ESC"
        if ch == b"\x03":
            raise KeyboardInterrupt
        try:
            return ch.decode("utf-8")
        except UnicodeDecodeError:
            return "?"

    def leer_linea(prompt):
        return input(prompt)

else:
    import termios
    import tty

    def leer_tecla():
        fd = sys.stdin.fileno()
        viejo = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                return {"[A": "ARR", "[B": "ABA", "[D": "IZQ", "[C": "DER"}.get(seq, "ESC")
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, viejo)

    def leer_linea(prompt):
        return input(prompt)


# ---------------------------------------------------------------
# Transporte serial hacia el Arduino
# ---------------------------------------------------------------
class Controlador:
    """Habla con calibrador.ino. En modo simulacion solo imprime."""

    def __init__(self, puerto=None, baud=115200, simular=False):
        self.simular = simular
        self.ser = None
        if simular:
            print("[SIM] modo simulacion: no se abre puerto serial")
            return

        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            sys.exit("Falta pyserial.  Instala con:  pip install pyserial")

        if puerto is None:
            puerto = self._autodetectar(list_ports)

        print(f"Abriendo {puerto} @ {baud} ...")
        self.ser = serial.Serial(puerto, baud, timeout=2)
        time.sleep(2.0)  # el Arduino se resetea al abrir el puerto
        self.ser.reset_input_buffer()

        resp = self.enviar("PING")
        if not resp.startswith("OK"):
            sys.exit(
                "El Arduino no responde PING.\n"
                f"  respondio: {resp!r}\n"
                "  Debe tener cargado calibrador.ino (para calibrar) o\n"
                "  milojos.ino v4 o superior (que tambien entiende PING).\n"
                "  Revisa tambien que el Monitor Serie del IDE este cerrado."
            )
        print(f"Arduino conectado: {resp}")
        print("I2C:", self.enviar("SCAN"))

    @staticmethod
    def _autodetectar(list_ports):
        puertos = list(list_ports.comports())
        if not puertos:
            sys.exit("No se encontro ningun puerto serial.")
        cands = [p for p in puertos
                 if any(k in (p.description or "").lower()
                        for k in ("arduino", "ch340", "usb", "wch", "silicon"))]
        lista = cands or puertos
        if len(lista) == 1:
            return lista[0].device
        print("\nPuertos disponibles:")
        for i, p in enumerate(lista):
            print(f"  [{i}] {p.device}  {p.description}")
        i = int(leer_linea("Elige puerto #: ").strip() or 0)
        return lista[i].device

    def enviar(self, cmd, espera_respuesta=True, timeout=None):
        if self.simular:
            return f"OK {cmd} [sim]"
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()
        if not espera_respuesta:
            return ""
        if timeout is not None:
            viejo = self.ser.timeout
            self.ser.timeout = timeout
            resp = self.ser.readline().decode(errors="ignore").strip()
            self.ser.timeout = viejo
            return resp
        return self.ser.readline().decode(errors="ignore").strip()

    def esperar_respuesta(self, timeout=10):
        """Lee la respuesta pendiente de un comando enviado sin esperar.
        Necesario cuando mandamos un movimiento y hacemos otra cosa mientras."""
        if self.simular:
            return "OK [sim]"
        viejo = self.ser.timeout
        self.ser.timeout = timeout
        try:
            return self.ser.readline().decode(errors="ignore").strip()
        finally:
            self.ser.timeout = viejo

    # --- comandos de alto nivel ---
    def mover(self, placa, canal, ang):
        return self.enviar(f"M {placa} {canal} {int(ang)}")

    def saltar(self, placa, canal, ang):
        return self.enviar(f"J {placa} {canal} {int(ang)}")

    def barrer(self, placa, canal, a, b):
        # el barrido tarda; damos timeout generoso
        return self.enviar(f"W {placa} {canal} {int(a)} {int(b)}", timeout=30)

    def liberar(self, placa, canal):
        return self.enviar(f"R {placa} {canal}")

    def liberar_todo(self):
        return self.enviar("RA")

    def pulsos(self, pmin, pmax):
        return self.enviar(f"L {int(pmin)} {int(pmax)}")

    def cerrar(self, liberar=False):
        """Por defecto NO libera: los servos se quedan sosteniendo su HOME."""
        if self.ser:
            try:
                if liberar:
                    self.liberar_todo()
            finally:
                self.ser.close()


# ---------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------
def canales_de_brazo(brazo):
    """Devuelve (placa_index, [canal0, canal1, canal2])."""
    placa = brazo // 3
    base = (brazo % 3) * SERVOS_POR_BRAZO
    return placa, [base + i for i in range(SERVOS_POR_BRAZO)]


def config_vacia(brazo):
    placa, canales = canales_de_brazo(brazo)
    return {
        "brazo": brazo,
        "placa_index": placa,
        "placa_addr": DIRECCIONES[placa],
        "canal_base": canales[0],
        "pulso_min": 150,
        "pulso_max": 600,
        "calibrado": None,
        "servos": [
            {
                "slot": i,
                "canal": canales[i],
                "articulacion": ARTICULACIONES_DEF[i],
                "min": 30,
                "max": 150,
                "home": 90,
                "invertido": False,
                "verificado": False,
            }
            for i in range(SERVOS_POR_BRAZO)
        ],
    }


def ruta_config(brazo):
    return os.path.join(DIR_CONFIG, f"brazo_{brazo}.json")


def cargar_config(brazo):
    ruta = ruta_config(brazo)
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # rellena claves nuevas si el JSON es de una version anterior
        base = config_vacia(brazo)
        for k, v in base.items():
            cfg.setdefault(k, v)
        # los JSON del esquema anterior (4 servos por brazo, 4 brazos por
        # placa) se recortan a 3 servos y toman el cableado actual
        cfg["servos"] = cfg["servos"][:SERVOS_POR_BRAZO]
        cfg["placa_index"] = base["placa_index"]
        cfg["placa_addr"] = base["placa_addr"]
        for i, s in enumerate(cfg["servos"]):
            s["canal"] = base["servos"][i]["canal"]
            for k, v in base["servos"][i].items():
                s.setdefault(k, v)
        return cfg
    return config_vacia(brazo)


def guardar_config(cfg):
    os.makedirs(DIR_CONFIG, exist_ok=True)
    cfg["calibrado"] = datetime.now().isoformat(timespec="seconds")
    ruta = ruta_config(cfg["brazo"])
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\n  Guardado -> {ruta}")
    return ruta


# ---------------------------------------------------------------
# Fase 1: verificar que cada canal es el servo que creemos
# ---------------------------------------------------------------
def verificar_canales(ctrl, cfg):
    placa = cfg["placa_index"]
    print("\n" + "=" * 62)
    print(f"  VERIFICACION DE CANALES - BRAZO {cfg['brazo']}  (placa {cfg['placa_addr']})")
    print("=" * 62)

    # Se repite la pasada COMPLETA mientras haya correcciones. Si dijiste que
    # el canal 0 no era la base sino el codo, el mapeo entero cambio de sentido
    # y hay que volver a preguntar por todos con los nombres nuevos.
    MAX_PASADAS = 6

    for pasada in range(1, MAX_PASADAS + 1):
        print(f"\n  ---------- PASADA {pasada} ----------")
        if pasada > 1:
            print("  Confirmando el mapeo corregido. Se pregunta de nuevo por TODOS")
            print("  los canales, ahora con los nombres que acabas de darme.")
        correcciones = 0

        for s in cfg["servos"]:
            canal = s["canal"]
            while True:
                print("\n" + "-" * 62)
                print(f"  BRAZO {cfg['brazo']} | pasada {pasada} | canal {canal} | "
                      f"slot {s['slot']} de {SERVOS_POR_BRAZO - 1}")
                print(f"  esperado: '{s['articulacion']}'")
                print("-" * 62)
                print("  El canal hara un barrido corto (75 -> 105 -> 75 grados).")
                print("  Observa QUE articulacion se movio y confirmalo despues.")
                print("  Los canales ya revisados se quedan sostenidos en 90 grados.")
                input("\n    Enter para hacer el barrido (Ctrl+C para abortar)... ")
                ctrl.mover(placa, canal, ANGULO_ARRANQUE)
                time.sleep(0.3)
                ctrl.barrer(placa, canal, 75, 105)

                resp = leer_linea(
                    f"    ¿Se movio '{s['articulacion']}'?  [s]i / [n]o, es otra / "
                    f"[r]epetir / [x] nada se movio: "
                ).strip().lower() or "s"

                if resp.startswith("s"):
                    s["verificado"] = True
                    break
                if resp.startswith("r"):
                    continue
                if resp.startswith("x"):
                    print("    ! Canal muerto o servo desconectado. Revisa cableado.")
                    if s["articulacion"] != "SIN_CONECTAR":
                        correcciones += 1
                    s["verificado"] = False
                    s["articulacion"] = "SIN_CONECTAR"
                    break
                nuevo = leer_linea(
                    f"    ¿Que articulacion es en realidad? {ARTICULACIONES_DEF} "
                    f"o escribe otra: "
                ).strip()
                if nuevo and nuevo != s["articulacion"]:
                    s["articulacion"] = nuevo
                    correcciones += 1
                s["verificado"] = True
                break

            # se queda sostenido en el centro, no lo soltamos
            if s["articulacion"] != "SIN_CONECTAR":
                ctrl.mover(placa, canal, ANGULO_ARRANQUE)
            else:
                ctrl.liberar(placa, canal)

        # --- balance de la pasada ---
        print("\n  Mapeo tras la pasada", pasada)
        for s in cfg["servos"]:
            marca = "OK" if s["verificado"] else "--"
            print(f"    [{marca}] canal {s['canal']} -> {s['articulacion']}")

        nombres = [s["articulacion"] for s in cfg["servos"]
                   if s["articulacion"] != "SIN_CONECTAR"]
        duplicados = sorted({n for n in nombres if nombres.count(n) > 1})
        if duplicados:
            print(f"\n  ! Hay articulaciones repetidas: {duplicados}")
            print("    Dos canales no pueden ser la misma articulacion.")

        if correcciones == 0 and not duplicados:
            print("\n  Pasada limpia: el mapeo coincide. Verificacion terminada.")
            return cfg

        if pasada == MAX_PASADAS:
            print(f"\n  ! {MAX_PASADAS} pasadas sin cerrar. Revisa el cableado con calma.")
            break

        print(f"\n  Hubo {correcciones} correccion(es)"
              + (" y nombres repetidos" if duplicados else "") + ".")
        r = leer_linea("  Enter para repetir la verificacion completa, "
                       "o [a] aceptar como esta: ").strip().lower()
        if r.startswith("a"):
            print("  Aceptado sin confirmar.")
            break

    return cfg


# ---------------------------------------------------------------
# Fase 2: jog en vivo para fijar zonas seguras
# ---------------------------------------------------------------
AYUDA = """
  ---------------- CONTROLES ----------------
   flechas IZQ/DER  o  a/d ....  -1 / +1 grado
   A / D ......................  -5 / +5 grados
   z / c ......................  -15 / +15 grados
   g ..........................  ir a un angulo exacto
   m ..........................  fijar MIN aqui
   x ..........................  fijar MAX aqui
   h ..........................  fijar HOME aqui
   t ..........................  probar recorrido MIN <-> MAX
   i ..........................  invertir sentido (flag)
   n ..........................  renombrar articulacion
   u ..........................  liberar servo (deja de forzar)
   ? ..........................  volver a mostrar esta ayuda
   ENTER ......................  guardar canal, ir al siguiente
   ESC ........................  salir sin terminar el brazo
  -------------------------------------------"""


def estado_linea(s, ang):
    inv = "INV" if s["invertido"] else "   "
    return (f"\r  canal {s['canal']:>2} [{s['articulacion']:<12}] "
            f"ang={ang:>3}  MIN={s['min']:>3} MAX={s['max']:>3} HOME={s['home']:>3} {inv}   ")


def mover_logico(ctrl, cfg, servo, ang):
    """Mueve un servo usando la convencion logica, aplicando la inversion."""
    return ctrl.mover(cfg["placa_index"], servo["canal"], angulo_fisico(servo, ang))


def sostener_en_home(ctrl, cfg, hechos):
    """Reafirma el HOME de los canales ya calibrados para que no se caigan."""
    for s in cfg["servos"]:
        if s["slot"] in hechos and s["articulacion"] != "SIN_CONECTAR":
            mover_logico(ctrl, cfg, s, s["home"])


def verificar_sentido(ctrl, cfg, s):
    """Comprueba que angulo bajo = <bajo> y angulo alto = <alto>.

    Si el servo esta montado al reves, marca 'invertido' y vuelve a probar
    hasta que el movimiento coincida con la convencion.
    """
    bajo, alto = convencion(s["slot"])
    centro = 90
    delta = 30

    print(f"\n  SENTIDO de '{s['articulacion']}' -> "
          f"angulo BAJO debe ser {bajo.upper()}, angulo ALTO debe ser {alto.upper()}")

    while True:
        mover_logico(ctrl, cfg, s, centro)
        time.sleep(0.6)
        print(f"    moviendo hacia el angulo bajo ({centro - delta}) ...")
        mover_logico(ctrl, cfg, s, centro - delta)
        time.sleep(0.8)

        r = leer_linea(f"    ¿Hacia donde se movio?  [1] {bajo}   [2] {alto}   "
                       f"[r] repetir   [s] saltar: ").strip().lower()

        if r == "r":
            continue
        if r == "s":
            break
        if r == "2":
            s["invertido"] = not s["invertido"]
            print(f"    -> servo montado al reves: invertido = {s['invertido']}. "
                  f"Repito la prueba para confirmar.")
            continue
        # r == "1" o Enter: coincide con la convencion
        print(f"    -> correcto (invertido = {s['invertido']})")
        break

    mover_logico(ctrl, cfg, s, centro)
    return s


def calibrar_zonas(ctrl, cfg):
    placa = cfg["placa_index"]
    print("\n" + "=" * 62)
    print(f"  ZONAS SEGURAS - BRAZO {cfg['brazo']}")
    print("=" * 62)

    hechos = set()

    for s in cfg["servos"]:
        if s["articulacion"] == "SIN_CONECTAR":
            print(f"\n  (canal {s['canal']} sin conectar, saltando)")
            continue

        canal = s["canal"]

        # Encabezado + ayuda COMPLETA en cada canal (el historial se pierde rapido)
        print("\n" + "=" * 62)
        print(f"  BRAZO {cfg['brazo']} | canal {canal} | slot {s['slot']} de "
              f"{SERVOS_POR_BRAZO - 1} | '{s['articulacion']}'")
        if hechos:
            listos = ", ".join(f"ch{cfg['servos'][i]['canal']}" for i in sorted(hechos))
            print(f"  Ya calibrados y sostenidos en HOME: {listos}")
        print("=" * 62)
        print(AYUDA)
        bajo, alto = convencion(s["slot"])
        print(f"  Convencion: angulo BAJO = {bajo}, angulo ALTO = {alto}")
        print("  Mueve poco a poco. En cuanto oigas el servo forzar, RETROCEDE")
        print("  y fija el limite unos 5 grados antes.")

        # Los ya calibrados vuelven a su HOME antes de tocar el siguiente
        sostener_en_home(ctrl, cfg, hechos)

        # Antes de tocar limites, confirmamos que el servo se mueve al derecho
        verificar_sentido(ctrl, cfg, s)

        ang = s["home"] if 0 <= s["home"] <= 180 else ANGULO_ARRANQUE
        mover_logico(ctrl, cfg, s, ang)
        print()
        sys.stdout.write(estado_linea(s, ang))
        sys.stdout.flush()

        while True:
            k = leer_tecla()
            delta = 0

            if k in ("IZQ", "a"):
                delta = -1
            elif k in ("DER", "d"):
                delta = 1
            elif k == "A":
                delta = -5
            elif k == "D":
                delta = 5
            elif k == "z":
                delta = -15
            elif k == "c":
                delta = 15
            elif k == "m":
                s["min"] = ang
            elif k == "x":
                s["max"] = ang
            elif k == "h":
                s["home"] = ang
            elif k == "i":
                # invertir de verdad: el servo se mueve al instante al espejo
                s["invertido"] = not s["invertido"]
                mover_logico(ctrl, cfg, s, ang)
            elif k == "u":
                ctrl.liberar(placa, canal)
            elif k == "g":
                print()
                try:
                    destino = int(leer_linea("    ir a angulo: ").strip())
                    ang = max(0, min(180, destino))
                    mover_logico(ctrl, cfg, s, ang)
                except ValueError:
                    pass
            elif k == "n":
                print()
                nuevo = leer_linea("    nombre de la articulacion: ").strip()
                if nuevo:
                    s["articulacion"] = nuevo
            elif k == "t":
                print()
                if s["min"] >= s["max"]:
                    print("    ! MIN debe ser menor que MAX")
                else:
                    print(f"    probando {s['min']} <-> {s['max']} ...")
                    ctrl.barrer(placa, canal,
                                angulo_fisico(s, s["min"]),
                                angulo_fisico(s, s["max"]))
                    ang = s["min"]
            elif k == "?":
                print()
                print(AYUDA)
            elif k == "ENTER":
                if s["min"] >= s["max"]:
                    print("\n    ! MIN >= MAX, corrige antes de continuar")
                    sys.stdout.write(estado_linea(s, ang))
                    sys.stdout.flush()
                    continue
                s["home"] = max(s["min"], min(s["max"], s["home"]))
                mover_logico(ctrl, cfg, s, s["home"])   # se queda sostenido aqui
                hechos.add(s["slot"])
                print(f"\n    canal {canal} listo -> sostenido en HOME {s['home']} grados")
                break
            elif k == "ESC":
                raise KeyboardInterrupt

            if delta:
                ang = max(0, min(180, ang + delta))
                mover_logico(ctrl, cfg, s, ang)

            sys.stdout.write(estado_linea(s, ang))
            sys.stdout.flush()

    # Brazo completo: todos los calibrados quedan sostenidos en su HOME
    sostener_en_home(ctrl, cfg, hechos)
    return cfg


# ---------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------
def resumen(cfg):
    print("\n  RESUMEN BRAZO", cfg["brazo"], f"(placa {cfg['placa_addr']})")
    print("  " + "-" * 56)
    print(f"  {'canal':<6}{'articulacion':<12}{'min':>5}{'max':>5}{'home':>6}{'inv':>5}"
          f"   {'sentido':<22}")
    for s in cfg["servos"]:
        bajo, alto = convencion(s["slot"])
        print(f"  {s['canal']:<6}{s['articulacion']:<12}{s['min']:>5}{s['max']:>5}"
              f"{s['home']:>6}{'si' if s['invertido'] else 'no':>5}"
              f"   {bajo} <-> {alto}")
    print("  " + "-" * 56)


# ---------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------
def estado_brazo(b):
    """'calibrado <fecha>' si el JSON ya tiene datos reales, si no 'plantilla'/'-'."""
    ruta = ruta_config(b)
    if not os.path.exists(ruta):
        return "-"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "JSON dañado"
    fecha = cfg.get("calibrado")
    return f"calibrado {fecha[:10]}" if fecha else "plantilla sin calibrar"


def elegir_brazo():
    print("\n  Brazos (4 servos cada uno):")
    for b in range(NUM_BRAZOS):
        placa, canales = canales_de_brazo(b)
        print(f"    [{b}] placa {DIRECCIONES[placa]}  canales {canales[0]}-{canales[-1]}"
              f"   {estado_brazo(b)}")
    txt = leer_linea("\n  Brazo a calibrar (q para salir): ").strip().lower()
    if txt in ("q", "quit", "salir"):
        return None
    try:
        b = int(txt)
        return b if 0 <= b < NUM_BRAZOS else None
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description="Calibrador de brazos MilOjos")
    ap.add_argument("--puerto", help="puerto serial, ej COM5 o /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--brazo", type=int, help="entra directo a este brazo (0-7)")
    ap.add_argument("--simular", action="store_true", help="sin hardware")
    ap.add_argument("--pulso-min", type=int, default=150)
    ap.add_argument("--pulso-max", type=int, default=600)
    ap.add_argument("--solo-zonas", action="store_true", help="salta la verificacion de canales")
    ap.add_argument("--liberar-al-salir", action="store_true",
                    help="suelta los servos al terminar (por defecto se quedan en HOME)")
    args = ap.parse_args()

    print("\n" + "=" * 62)
    print("  MILOJOS - CALIBRADOR DE BRAZOS")
    print("=" * 62)

    ctrl = Controlador(args.puerto, args.baud, args.simular)
    ctrl.pulsos(args.pulso_min, args.pulso_max)

    try:
        while True:
            brazo = args.brazo if args.brazo is not None else elegir_brazo()
            if brazo is None:
                break

            cfg = cargar_config(brazo)
            cfg["pulso_min"] = args.pulso_min
            cfg["pulso_max"] = args.pulso_max

            try:
                if not args.solo_zonas:
                    verificar_canales(ctrl, cfg)
                calibrar_zonas(ctrl, cfg)
            except KeyboardInterrupt:
                print("\n\n  Interrumpido.")
                if (leer_linea("  ¿Guardar lo que llevas? [s/N]: ").strip().lower() or "n").startswith("s"):
                    guardar_config(cfg)
                break

            resumen(cfg)
            guardar_config(cfg)

            if args.brazo is not None:
                break
    finally:
        if args.liberar_al_salir:
            ctrl.liberar_todo()
            ctrl.cerrar(liberar=True)
            print("\n  Servos liberados. Listo.\n")
        else:
            ctrl.cerrar(liberar=False)
            print("\n  Servos sostenidos en HOME (--liberar-al-salir para soltarlos).\n")


if __name__ == "__main__":
    main()
