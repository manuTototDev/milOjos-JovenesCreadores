/*
 * CALIBRADOR - MilOjos
 * ---------------------------------------------------------------
 * Sketch DEDICADO a calibracion. No tiene movimiento autonomo:
 * solo obedece comandos por serial desde python/calibrar_brazos.py
 *
 * Hardware: 3x PCA9685 en cadena I2C
 *   placa 0 -> 0x40  (brazos 0..2, canales 0..8)
 *   placa 1 -> 0x41  (brazos 3..5, canales 0..8)
 *   placa 2 -> 0x42  (brazos 6..8, canales 0..8)
 *
 * PROTOCOLO (lineas terminadas en \n, respuesta siempre una linea)
 *   PING                  -> OK CALIB v1
 *   SCAN                  -> OK SCAN 0x40,0x41,0x42
 *   M <placa> <ch> <ang>  -> OK M p ch ang      mueve suave a ese angulo
 *   J <placa> <ch> <ang>  -> OK J p ch ang      salto inmediato (sin rampa)
 *   W <placa> <ch> <a> <b>-> OK W               barrido lento a->b->a (identificar)
 *   R <placa> <ch>        -> OK R p ch          libera (sin PWM) ese canal
 *   RA                    -> OK RA              libera TODOS los canales
 *   L <pmin> <pmax>       -> OK L pmin pmax     rango de pulso global (ticks)
 *   U <placa> <ch> <tick> -> OK U               pulso crudo, para afinar L
 *   F <hz>                -> OK F hz            frecuencia PWM
 *   Cualquier otra cosa   -> ERR ...
 * ---------------------------------------------------------------
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define NUM_PLACAS 3
const uint8_t DIRECCIONES[NUM_PLACAS] = {0x40, 0x41, 0x42};

Adafruit_PWMServoDriver pwm[NUM_PLACAS] = {
  Adafruit_PWMServoDriver(0x40),
  Adafruit_PWMServoDriver(0x41),
  Adafruit_PWMServoDriver(0x42)
};

// Rango de pulso global (ticks @ 50Hz). Ajustable en vivo con L.
int pulsoMin = 150;
int pulsoMax = 600;

// Ultima posicion conocida de cada canal, para hacer rampas suaves.
// -1 = canal liberado / posicion desconocida.
int ultimoAng[NUM_PLACAS][16];

const int VEL_RAMPA_MS = 12;   // ms por grado en movimiento suave
const int VEL_BARRIDO_MS = 18; // ms por grado en el barrido de identificacion

int anguloAPulso(int ang) {
  ang = constrain(ang, 0, 180);
  return map(ang, 0, 180, pulsoMin, pulsoMax);
}

void escribirAngulo(uint8_t p, uint8_t ch, int ang) {
  ang = constrain(ang, 0, 180);
  pwm[p].setPWM(ch, 0, anguloAPulso(ang));
  ultimoAng[p][ch] = ang;
}

// Movimiento con rampa: si no sabemos donde estaba, saltamos y ya.
void moverSuave(uint8_t p, uint8_t ch, int destino) {
  destino = constrain(destino, 0, 180);
  int actual = ultimoAng[p][ch];
  if (actual < 0) {
    escribirAngulo(p, ch, destino);
    return;
  }
  int paso = (destino > actual) ? 1 : -1;
  while (actual != destino) {
    actual += paso;
    escribirAngulo(p, ch, actual);
    delay(VEL_RAMPA_MS);
  }
}

void barrido(uint8_t p, uint8_t ch, int a, int b) {
  a = constrain(a, 0, 180);
  b = constrain(b, 0, 180);
  moverSuave(p, ch, a);
  delay(200);
  int paso = (b > a) ? 1 : -1;
  for (int x = a; x != b; x += paso) { escribirAngulo(p, ch, x); delay(VEL_BARRIDO_MS); }
  delay(250);
  for (int x = b; x != a; x -= paso) { escribirAngulo(p, ch, x); delay(VEL_BARRIDO_MS); }
  escribirAngulo(p, ch, a);
}

void liberar(uint8_t p, uint8_t ch) {
  pwm[p].setPWM(ch, 0, 0);
  ultimoAng[p][ch] = -1;
}

void liberarTodo() {
  for (uint8_t p = 0; p < NUM_PLACAS; p++)
    for (uint8_t ch = 0; ch < 16; ch++) liberar(p, ch);
}

bool placaValida(int p)  { return p >= 0 && p < NUM_PLACAS; }
bool canalValido(int ch) { return ch >= 0 && ch < 16; }

// Parte una linea en hasta 5 tokens separados por espacio.
int trocear(String s, String* out, int maxTok) {
  int n = 0, ini = 0;
  s.trim();
  while (n < maxTok) {
    int sp = s.indexOf(' ', ini);
    if (sp == -1) { out[n++] = s.substring(ini); break; }
    out[n++] = s.substring(ini, sp);
    ini = sp + 1;
  }
  return n;
}

void escanearI2C() {
  String encontradas = "";
  for (uint8_t dir = 0x40; dir <= 0x7F; dir++) {
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) {
      if (encontradas.length()) encontradas += ",";
      encontradas += "0x" + String(dir, HEX);
    }
  }
  Serial.println("OK SCAN " + (encontradas.length() ? encontradas : String("ninguna")));
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  Wire.begin();
  for (uint8_t p = 0; p < NUM_PLACAS; p++) {
    pwm[p].begin();
    pwm[p].setPWMFreq(50);
    for (uint8_t ch = 0; ch < 16; ch++) ultimoAng[p][ch] = -1;
  }
  liberarTodo();  // arrancamos con todo suelto: nada se mueve solo
  delay(50);
  Serial.println("OK CALIB v1 listo");
}

void loop() {
  if (!Serial.available()) return;

  String linea = Serial.readStringUntil('\n');
  linea.trim();
  if (linea.length() == 0) return;

  String t[5];
  int n = trocear(linea, t, 5);
  String cmd = t[0];
  cmd.toUpperCase();

  if (cmd == "PING") {
    Serial.println("OK CALIB v1");
  }
  else if (cmd == "SCAN") {
    escanearI2C();
  }
  else if (cmd == "RA") {
    liberarTodo();
    Serial.println("OK RA");
  }
  else if (cmd == "L" && n >= 3) {
    int a = t[1].toInt(), b = t[2].toInt();
    if (a < 80 || b > 700 || a >= b) { Serial.println("ERR rango de pulso invalido"); return; }
    pulsoMin = a; pulsoMax = b;
    Serial.println("OK L " + String(pulsoMin) + " " + String(pulsoMax));
  }
  else if (cmd == "F" && n >= 2) {
    int hz = constrain(t[1].toInt(), 24, 400);
    for (uint8_t p = 0; p < NUM_PLACAS; p++) pwm[p].setPWMFreq(hz);
    Serial.println("OK F " + String(hz));
  }
  else if ((cmd == "M" || cmd == "J") && n >= 4) {
    int p = t[1].toInt(), ch = t[2].toInt(), ang = t[3].toInt();
    if (!placaValida(p) || !canalValido(ch)) { Serial.println("ERR placa/canal"); return; }
    if (cmd == "M") moverSuave(p, ch, ang); else escribirAngulo(p, ch, ang);
    Serial.println("OK " + cmd + " " + String(p) + " " + String(ch) + " " + String(constrain(ang, 0, 180)));
  }
  else if (cmd == "W" && n >= 5) {
    int p = t[1].toInt(), ch = t[2].toInt(), a = t[3].toInt(), b = t[4].toInt();
    if (!placaValida(p) || !canalValido(ch)) { Serial.println("ERR placa/canal"); return; }
    barrido(p, ch, a, b);
    Serial.println("OK W " + String(p) + " " + String(ch));
  }
  else if (cmd == "R" && n >= 3) {
    int p = t[1].toInt(), ch = t[2].toInt();
    if (!placaValida(p) || !canalValido(ch)) { Serial.println("ERR placa/canal"); return; }
    liberar(p, ch);
    Serial.println("OK R " + String(p) + " " + String(ch));
  }
  else if (cmd == "U" && n >= 4) {
    int p = t[1].toInt(), ch = t[2].toInt(), tick = constrain(t[3].toInt(), 0, 4095);
    if (!placaValida(p) || !canalValido(ch)) { Serial.println("ERR placa/canal"); return; }
    pwm[p].setPWM(ch, 0, tick);
    ultimoAng[p][ch] = -1;  // posicion en angulos ya no es confiable
    Serial.println("OK U " + String(p) + " " + String(ch) + " " + String(tick));
  }
  else {
    Serial.println("ERR comando desconocido: " + cmd);
  }
}
