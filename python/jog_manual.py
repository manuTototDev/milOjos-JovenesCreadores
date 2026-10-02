#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jog_manual.py - MilOjos
===============================================================
Interfaz minima con sliders para mover a mano los canales de una
placa PCA9685, en vivo, via el sketch arduino/calibrador/calibrador.ino.

Pensado para diagnostico rapido: ver que servo responde a que canal,
sin pasar por todo el flujo de calibrar_brazos.py.

Uso:
    python jog_manual.py                  # placa 0 (0x40), canales 0-2
    python jog_manual.py --placa 1        # placa 1 (0x41), canales 0-2
    python jog_manual.py --placa 2        # placa 2 (0x42), canales 0-2
    python jog_manual.py --canales 0-7    # otro rango de canales
    python jog_manual.py --puerto COM6
===============================================================
"""

import argparse
import os
import sys

import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrar_brazos import Controlador


class JogApp:
    def __init__(self, root, ctrl, placa, canales):
        self.root = root
        self.ctrl = ctrl
        self.placa = placa
        self.canales = canales
        self._pendiente = {}
        self._despues_id = None

        root.title(f"MilOjos - Jog manual (placa 0x{40 + placa:02x}, canales {canales[0]}-{canales[-1]})")

        self.sliders = {}
        for i, ch in enumerate(canales):
            tk.Label(root, text=f"canal {ch}", width=10).grid(row=i, column=0, padx=8, pady=4)
            s = tk.Scale(root, from_=0, to=180, orient="horizontal", length=320,
                         command=lambda val, ch=ch: self.mover(ch, val))
            s.set(90)
            s.grid(row=i, column=1, padx=8, pady=4)
            self.sliders[ch] = s
            tk.Button(root, text="Liberar", width=8,
                      command=lambda ch=ch: self.liberar(ch)).grid(row=i, column=2, padx=8, pady=4)

        tk.Button(root, text="Liberar todos", command=self.liberar_todos).grid(
            row=len(canales), column=0, columnspan=3, pady=8)

        self.log = tk.Text(root, height=8, width=64, state="disabled")
        self.log.grid(row=len(canales) + 1, column=0, columnspan=3, padx=8, pady=8)

    def _log(self, texto):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def mover(self, ch, val):
        # throttle: guarda el ultimo valor pedido por canal y lo manda poco despues,
        # asi arrastrar el slider no inunda el puerto serial de comandos.
        self._pendiente[ch] = int(float(val))
        if self._despues_id is None:
            self._despues_id = self.root.after(30, self._enviar_pendientes)

    def _enviar_pendientes(self):
        self._despues_id = None
        for ch, ang in list(self._pendiente.items()):
            resp = self.ctrl.saltar(self.placa, ch, ang)
            self._log(f"J {self.placa} {ch} {ang} -> {resp}")
        self._pendiente.clear()

    def liberar(self, ch):
        resp = self.ctrl.liberar(self.placa, ch)
        self._log(f"R {self.placa} {ch} -> {resp}")

    def liberar_todos(self):
        resp = self.ctrl.liberar_todo()
        self._log(f"RA -> {resp}")

    def cerrar(self):
        self.ctrl.cerrar(liberar=False)
        self.root.destroy()


def parse_canales(txt):
    a, b = txt.split("-")
    return list(range(int(a), int(b) + 1))


def main():
    ap = argparse.ArgumentParser(description="Jog manual con sliders - MilOjos")
    ap.add_argument("--puerto", help="puerto serial, ej COM6")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--placa", type=int, default=0, choices=[0, 1, 2])
    ap.add_argument("--canales", default="0-2", help="rango, ej 0-2 o 3-5")
    args = ap.parse_args()

    canales = parse_canales(args.canales)

    ctrl = Controlador(puerto=args.puerto, baud=args.baud, simular=False)

    root = tk.Tk()
    app = JogApp(root, ctrl, args.placa, canales)
    root.protocol("WM_DELETE_WINDOW", app.cerrar)
    root.mainloop()


if __name__ == "__main__":
    main()
