#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_header.py - MilOjos
Lee Dev/config/brazo_*.json y escribe arduino/config_brazos.h
para que el sketch principal use los limites calibrados.

    python generar_header.py
"""

import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrar_brazos import ARTICULACIONES_DEF, SENTIDOS, canales_de_brazo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CONFIG = os.path.join(RAIZ, "config")
# El header vive junto al sketch que lo usa (el IDE de Arduino solo ve los
# archivos de la carpeta del sketch).
SALIDA = os.path.join(RAIZ, "arduino", "milojos", "config_brazos.h")

NUM_BRAZOS = 9
SERVOS_POR_BRAZO = 3


def main():
    archivos = sorted(glob.glob(os.path.join(DIR_CONFIG, "brazo_*.json")))
    if not archivos:
        raise SystemExit(f"No hay JSONs en {DIR_CONFIG}. Corre calibrar_brazos.py primero.")

    brazos = {}
    for ruta in archivos:
        with open(ruta, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        brazos[cfg["brazo"]] = cfg

    faltan = [b for b in range(NUM_BRAZOS) if b not in brazos]

    L = []
    L.append("// GENERADO POR python/generar_header.py - NO EDITAR A MANO")
    L.append(f"// {datetime.now().isoformat(timespec='seconds')}")
    if faltan:
        L.append(f"// AVISO: brazos sin calibrar (valores por defecto): {faltan}")
    L.append("#pragma once")
    L.append("")
    L.append(f"#define NUM_BRAZOS {NUM_BRAZOS}")
    L.append(f"#define SERVOS_POR_BRAZO {SERVOS_POR_BRAZO}")
    L.append(f"#define TOTAL_SERVOS (NUM_BRAZOS * SERVOS_POR_BRAZO)")
    L.append("")

    pmin = next(iter(brazos.values())).get("pulso_min", 150)
    pmax = next(iter(brazos.values())).get("pulso_max", 600)
    L.append(f"#define SERVOMIN {pmin}")
    L.append(f"#define SERVOMAX {pmax}")
    L.append("")
    L.append("// indice global = brazo * SERVOS_POR_BRAZO + slot")
    L.append("// placa 0 -> 0x40 (brazos 0-2), placa 1 -> 0x41 (brazos 3-5), placa 2 -> 0x42 (brazos 6-8)")
    L.append("")

    def fila(clave, defecto):
        vals = []
        for b in range(NUM_BRAZOS):
            cfg = brazos.get(b)
            for s in range(SERVOS_POR_BRAZO):
                if cfg:
                    vals.append(cfg["servos"][s][clave])
                else:
                    vals.append(defecto)
        return vals

    def emitir(tipo, nombre, vals, fmt=str):
        cuerpo = []
        for b in range(NUM_BRAZOS):
            trozo = vals[b * SERVOS_POR_BRAZO:(b + 1) * SERVOS_POR_BRAZO]
            cuerpo.append("  " + ", ".join(fmt(v) for v in trozo) + f",  // brazo {b}")
        L.append(f"const {tipo} {nombre}[TOTAL_SERVOS] = {{")
        L.extend(cuerpo)
        L.append("};")
        L.append("")

    emitir("uint8_t", "SERVO_PLACA", [canales_de_brazo(b)[0] for b in range(NUM_BRAZOS) for _ in range(SERVOS_POR_BRAZO)])
    # Canal segun el cableado 3 brazos por placa (no el del JSON, que
    # viene del esquema anterior de 4 servos por brazo).
    emitir("uint8_t", "SERVO_CANAL", [c for b in range(NUM_BRAZOS) for c in canales_de_brazo(b)[1]])
    emitir("int16_t", "SERVO_MIN", fila("min", 30))
    emitir("int16_t", "SERVO_MAX", fila("max", 150))
    emitir("int16_t", "SERVO_HOME", fila("home", 90))
    emitir("bool", "SERVO_INVERTIDO", fila("invertido", False), fmt=lambda v: "true" if v else "false")

    # Los nombres van como COMENTARIO, no como array: con 27 servos, guardar
    # 27 punteros mas las cadenas se come cientos de bytes de RAM y en tiempo
    # de ejecucion no los usa nadie.
    nombres = fila("articulacion", "n/a")
    L.append("// Mapa de articulaciones (solo referencia, no ocupa RAM):")
    for b in range(NUM_BRAZOS):
        trozo = nombres[b * SERVOS_POR_BRAZO:(b + 1) * SERVOS_POR_BRAZO]
        idx0 = b * SERVOS_POR_BRAZO
        L.append(f"//   brazo {b} (indices {idx0}-{idx0 + SERVOS_POR_BRAZO - 1}): "
                 + ", ".join(trozo))
    L.append("")
    L.append("// ---------------------------------------------------------------")
    L.append("// CONVENCION DE SENTIDO (angulos LOGICOS, iguales para los 9 brazos)")
    for slot in range(SERVOS_POR_BRAZO):
        bajo, alto = SENTIDOS.get(slot, ("menos", "mas"))
        nombre = ARTICULACIONES_DEF[slot] if slot < len(ARTICULACIONES_DEF) else f"slot{slot}"
        L.append(f"//   slot {slot} ({nombre}): angulo bajo = {bajo}, angulo alto = {alto}")
    L.append("// Si un servo quedo atornillado al reves, SERVO_INVERTIDO[i] es true")
    L.append("// y anguloFisico() le da la vuelta. Trabaja SIEMPRE en logicos.")
    L.append("// ---------------------------------------------------------------")
    L.append("")
    L.append("// Recorta un angulo logico a la zona segura del servo global i")
    L.append("inline int16_t zonaSegura(uint8_t i, int16_t ang) {")
    L.append("  if (ang < SERVO_MIN[i]) return SERVO_MIN[i];")
    L.append("  if (ang > SERVO_MAX[i]) return SERVO_MAX[i];")
    L.append("  return ang;")
    L.append("}")
    L.append("")
    L.append("// Convierte angulo LOGICO -> angulo FISICO que se manda al servo")
    L.append("inline int16_t anguloFisico(uint8_t i, int16_t ang) {")
    L.append("  return SERVO_INVERTIDO[i] ? (180 - ang) : ang;")
    L.append("}")
    L.append("")
    L.append("// Lo normal: recortar a zona segura y traducir de un golpe")
    L.append("inline int16_t anguloSeguroFisico(uint8_t i, int16_t ang) {")
    L.append("  return anguloFisico(i, zonaSegura(i, ang));")
    L.append("}")
    L.append("")

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"Escrito: {SALIDA}")
    print(f"Brazos calibrados: {sorted(brazos)}")
    if faltan:
        print(f"Sin calibrar (defaults): {faltan}")


if __name__ == "__main__":
    main()
