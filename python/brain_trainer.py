import cv2
import numpy as np
import os
import time
import serial
import serial.tools.list_ports
import csv
import threading
from insightface.app import FaceAnalysis

# --- CONFIGURACION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PESOS_FILE = os.path.join(BASE_DIR, "pesos_robot.npy")
CSV_DATOS = os.path.join(BASE_DIR, "training_data.csv")
LR = 0.02

class BrainTrainer:
    def __init__(self):
        self.pesos = np.zeros((2, 2))
        self.fase_calib = 0
        self.timer_fase = 0
        self.error_inicial_fase = np.zeros(2)
        self.aciertos = 0
        self.fallos = 0
        self.last_dist = 0
        self.last_move = np.zeros(2)
        self.load_pesos()

    def load_pesos(self):
        if os.path.exists(PESOS_FILE):
            try: self.pesos = np.load(PESOS_FILE)
            except: self.pesos = np.zeros((2,2))

    def reset_pesos(self):
        self.pesos = np.zeros((2, 2))
        self.fase_calib = 0
        print("SISTEMA: Cerebro Reseteado.")

    def update(self, error_input, distancia_px, ahora):
        status_msg = "SISTEMA LISTO"
        reward_color = (0, 255, 255)
        step_v, step_h = 0, 0

        if self.fase_calib == 0:
            status_msg = "FASE 0: QUIETO - MIDIENDO"
            if self.timer_fase == 0: self.timer_fase = ahora
            if ahora - self.timer_fase > 2.0:
                self.fase_calib = 1
                self.timer_fase = ahora
                self.error_inicial_fase = error_input
                step_h = 10.0 # Giro de prueba peque/o
                print("SISTEMA: Iniciando Fase 1 (Base)")

        elif self.fase_calib == 1:
            status_msg = "FASE 1: MIDIENDO BASE..."
            if ahora - self.timer_fase > 1.2:
                diff_err = error_input - self.error_inicial_fase
                self.pesos[1, 0] = diff_err[0] / 10.0 
                self.pesos[1, 1] = diff_err[1] / 10.0
                self.fase_calib = 2
                self.timer_fase = ahora
                self.error_inicial_fase = error_input
                step_v = 10.0
                print("SISTEMA: Iniciando Fase 2 (Vertical)")

        elif self.fase_calib == 2:
            status_msg = "FASE 2: MIDIENDO CAMV..."
            if ahora - self.timer_fase > 1.2:
                diff_err = error_input - self.error_inicial_fase
                self.pesos[0, 0] = diff_err[0] / 10.0 
                self.pesos[0, 1] = diff_err[1] / 10.0
                self.pesos = -np.clip(self.pesos, -0.6, 0.6)
                self.fase_calib = 3
                np.save(PESOS_FILE, self.pesos)
                print("SISTEMA: Calibracion Exitosa.")

        elif self.fase_calib == 3:
            delta_dist = self.last_dist - distancia_px
            if self.last_dist > 0 and distancia_px > 30:
                if delta_dist > 0.8:
                    self.aciertos += 1
                    status_msg = "+++ PREMIO +++"
                    reward_color = (0, 255, 0)
                    self.pesos += LR * np.outer(self.last_move * 0.1, error_input)
                elif delta_dist < -1.5:
                    self.fallos += 1
                    status_msg = "--- CASTIGO ---"
                    reward_color = (0, 0, 255)
                    self.pesos -= LR * 2.0 * np.outer(self.last_move * 0.1, error_input)

            mov_raw = np.dot(self.pesos, error_input)
            step_v = mov_raw[0] * 55 # Velocidad de seguimiento (Mas agil)
            step_h = mov_raw[1] * 55

        self.last_dist = distancia_px
        self.last_move = np.array([step_v, step_h])
        return step_v, step_h, status_msg, reward_color

    def draw_hud(self, canvas, status_msg, reward_color, distancia_px):
        cv2.putText(canvas, "MIL OJOS - BRAIN TRAINER v2.0", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        cv2.putText(canvas, f"STATUS: {status_msg}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, reward_color, 2)
        cv2.putText(canvas, f"D_PX: {int(distancia_px)}", (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(canvas, f"W_CAMV: {np.round(self.pesos[0],2)}", (10, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        cv2.putText(canvas, f"W_BASE: {np.round(self.pesos[1],2)}", (10, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        cv2.imshow("Red Neuronal - Refuerzo", canvas)

# --- VIDEO STREAM ---
class VideoStream:
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        self.frame = None
        self.stopped = False
    def start(self):
        threading.Thread(target=self.update, daemon=True).start()
        return self
    def update(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            if ret: self.frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    def read(self): return self.frame
    def stop(self): self.stopped = True; self.cap.release()

if __name__ == "__main__":
    print("SISTEMA: Cargando IA...")
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    
    vs = VideoStream().start()
    trainer = BrainTrainer()
    
    print("SISTEMA: Conectando Arduino en COM6...")
    try:
        arduino = serial.Serial('COM6', 115200, timeout=0.01)
        time.sleep(2)
        print("CONECTADO A ARDUINO.")
    except:
        arduino = None
        print("ERROR: Arduino no encontrado en COM6.")

    posArm2 = [90.0, 60.0, 70.0, 90.0]
    targetArm2 = [90.0, 60.0, 70.0, 90.0]
    last_print = 0

    try:
        while True:
            frame = vs.read()
            if frame is None: continue
            
            faces = app.get(frame)
            ahora = time.time()
            cx, cy = frame.shape[1]//2, frame.shape[0]//2

            if faces:
                f = sorted(faces, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]), reverse=True)[0]
                tx, ty = int((f.bbox[0]+f.bbox[2])//2), int((f.bbox[1]+f.bbox[3])//2)
                err_x_rel, err_y_rel = (cx-tx)/(cx), (cy-ty)/(cy)
                dist = np.sqrt((cx-tx)**2 + (cy-ty)**2)
                
                step_v, step_h, status, color = trainer.update(np.array([err_x_rel, err_y_rel]), dist, ahora)
                targetArm2[0] += step_h
                targetArm2[2] += step_v
                
                # Visual
                cv2.line(frame, (cx, cy), (tx, ty), (0,255,0), 2)
                cv2.putText(frame, "ROSTRO DETECTADO", (cx-80, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(frame, status, (10, 400), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            else:
                cv2.putText(frame, "ESPERANDO ROSTRO...", (cx-80, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # Enviar Arduino (Siempre envia para mantener servos vivos)
            if arduino:
                for i in range(4):
                    targetArm2[i] = np.clip(targetArm2[i], 20, 160)
                    posArm2[i] += (targetArm2[i] - posArm2[i]) * 0.1
                
                cmd = f"$90,60,50,90,{int(posArm2[0])},{int(posArm2[1])},{int(posArm2[2])},{int(posArm2[3])},90,70,60,90,90,65,55,90,1\n"
                arduino.write(cmd.encode())
                
                if ahora - last_print > 1.0:
                    print(f"ENVIANDO ANGULOS: B2_Base={int(posArm2[0])} B2_Tilt={int(posArm2[2])}")
                    last_print = ahora

            cv2.imshow("ESTACION DE ENTRENAMIENTO MIL OJOS", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'): break
            if key == ord('r'): trainer.reset_pesos()

    except KeyboardInterrupt: pass
    finally:
        vs.stop(); cv2.destroyAllWindows()
        if arduino: arduino.close()
