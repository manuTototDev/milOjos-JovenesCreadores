#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

#define SERVOMIN  150 
#define SERVOMAX  600 

const int MIN_B = 15, MAX_B = 165;
const int MIN_H = 45, MAX_H = 85;
const int MIN_V = 15, MAX_V = 140;

// Estado de los 16 canales (4 brazos x 4 servos)
float pos[16] = {90, 60, 45, 90, 90, 60, 45, 90, 90, 60, 45, 90, 90, 60, 45, 90};
float targetPos[16] = {90, 60, 45, 90, 90, 60, 45, 90, 90, 60, 45, 90, 90, 60, 45, 90};
unsigned long ultimoPulsoSerial = 0;
bool modoManual = false;

// Variables de búsqueda
float t[16] = {0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500};
float tVel = 0;

float noise1D(float x) {
  int x0 = (int)x;
  float t_val = x - x0;
  float g0 = ((x0 * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483647.0;
  float g1 = (((x0 + 1) * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483647.0;
  return g0 + (3*t_val*t_val - 2*t_val*t_val*t_val) * (g1 - g0);
}

void actualizarServos() {
  for(int i=0; i<16; i++) {
    pwm.setPWM(i, 0, map(int(pos[i]), 0, 180, SERVOMIN, SERVOMAX));
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(20);
  pwm.begin();
  pwm.setPWMFreq(50);
  for(int i=0; i<16; i++) targetPos[i] = pos[i];
  actualizarServos();
}

void loop() {
  unsigned long ahora = millis();

  if (Serial.available() > 0) {
    if (Serial.peek() == '$') {
      Serial.read(); // Quitar el '$'
      String datos = Serial.readStringUntil('\n');
      
      int indice = 0;
      int startPos = 0;
      int endPos = datos.indexOf(',');
      
      while (endPos != -1 && indice < 16) {
        targetPos[indice] = datos.substring(startPos, endPos).toFloat();
        startPos = endPos + 1;
        endPos = datos.indexOf(',', startPos);
        indice++;
      }
      
      if (indice >= 12) {
        int m = datos.substring(startPos).toInt();
        if (m == 1) {
          modoManual = true;
          ultimoPulsoSerial = ahora;
          for(int i=0; i<16; i++) {
            targetPos[i] = constrain(targetPos[i], 0, 180);
          }
        }
      }
    } else {
      Serial.read();
    }
  }

  // Failsafe: SI no hay serial en 3 segundos, volver a búsqueda suave
  if (ahora - ultimoPulsoSerial > 3000) {
    modoManual = false;
  }

  if (!modoManual) {
    tVel += 0.004;
    float dt = map(pow(noise1D(tVel), 1.5) * 1000, 0, 1000, 2, 15) / 1000.0;
    
    for(int i=0; i<16; i++) {
        t[i] += dt * (1.0 + (i * 0.015));
        int tipo = i % 4;
        if (tipo == 0 || tipo == 3) targetPos[i] = map(noise1D(t[i]) * 100, 0, 100, MIN_B, MAX_B);
        else if (tipo == 1)         targetPos[i] = map(noise1D(t[i]) * 100, 0, 100, MIN_H, MAX_H);
        else if (tipo == 2)         targetPos[i] = map(noise1D(t[i]) * 100, 0, 100, MIN_V, MAX_V);
    }
  }

  // INTERPOLACIÓN GLOBAL PARA MÁXIMA SUAVIDAD
  float factorSuavizado = modoManual ? 0.08 : 0.01;
  for(int i=0; i<16; i++) {
    pos[i] += (targetPos[i] - pos[i]) * factorSuavizado;
  }

  actualizarServos();
  delay(5);
}