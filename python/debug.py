import cv2
import serial
import time
import numpy as np

# Conexión Serial
try:
    arduino = serial.Serial('COM6', 115200, timeout=0.1)
    time.sleep(2)
    arduino.reset_input_buffer()
    print("Consola de Debug: Brazo1(0-3), Brazo2(4-7), Brazo3(8-11), Brazo4(12-15)")
except Exception as e:
    print(f"Error Serial: {e}")
    exit()

def nothing(x): pass

WINDOW_NAME = 'CONTROL MANUAL BRAZOS'
cv2.namedWindow(WINDOW_NAME)

# Crear Sliders (4 por cada uno de los 4 brazos)
for arm in range(1, 5):
    cv2.createTrackbar(f'B{arm}_Base', WINDOW_NAME, 90, 180, nothing)
    cv2.createTrackbar(f'B{arm}_Homb', WINDOW_NAME, 60, 180, nothing)
    cv2.createTrackbar(f'B{arm}_Vert', WINDOW_NAME, 45, 180, nothing)
    cv2.createTrackbar(f'B{arm}_Horz', WINDOW_NAME, 90, 180, nothing)

try:
    while True:
        # Recolectar valores de los sliders
        vals = []
        for arm in range(1, 5):
            vals.append(cv2.getTrackbarPos(f'B{arm}_Base', WINDOW_NAME))
            vals.append(cv2.getTrackbarPos(f'B{arm}_Homb', WINDOW_NAME))
            vals.append(cv2.getTrackbarPos(f'B{arm}_Vert', WINDOW_NAME))
            vals.append(cv2.getTrackbarPos(f'B{arm}_Horz', WINDOW_NAME))

        # Enviar paquete con caracter de sincronía '$'
        # El formato es: $v1,v2...v16,1\n
        cmd = "$" + ",".join(map(str, vals)) + ",1\n"
        arduino.write(cmd.encode())
        
        # Monitor visual
        img = np.zeros((150, 550, 3), np.uint8)
        cv2.putText(img, f"Enviando 16 canales + Modo 1", (20, 50), 1, 1.2, (0,255,0), 2)
        cv2.putText(img, f"Pulsa 'q' para salir", (20, 100), 1, 1, (255,255,255), 1)
        cv2.imshow('STATUS', img)

        if cv2.waitKey(40) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    pass
finally:
    arduino.close()
    cv2.destroyAllWindows()
