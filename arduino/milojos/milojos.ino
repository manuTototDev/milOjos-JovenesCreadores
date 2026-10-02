/*
 * MIL OJOS v5 - sketch principal
 * ---------------------------------------------------------------
 * 9 brazos x 3 servos = 27 canales sobre 3 PCA9685 (0x40, 0x41 y 0x42).
 *
 * Diferencias contra la v3:
 *   - Maneja las TRES placas (la v3 solo instanciaba una: 16 canales).
 *   - Los limites vienen de config_brazos.h, generado por la calibracion
 *     real de cada servo, en vez de tres constantes globales a ojo.
 *   - La zona segura se aplica AQUI, en el firmware. Antes solo la
 *     respetaba init.py; si Python se caia o alguien escribia a mano por
 *     el monitor serie, el servo se iba al tope y forzaba.
 *   - Respeta SERVO_INVERTIDO: los servos montados al reves se corrigen
 *     en software, asi todo el sistema habla en angulos logicos.
 *   - Sin objetos String: parseo con buffer fijo, para no fragmentar la
 *     RAM (con 27 servos el margen es estrecho en placas chicas).
 *
 * Todo lo que se maneja aqui esta en ANGULOS LOGICOS. La convencion y la
 * traduccion a angulo fisico viven en config_brazos.h.
 *
 * PROTOCOLO SERIAL (compatible con el init.py actual)
 *   $a0,a1,...,aN,modo\n
 *     N angulos (hasta 27) aplicados a los servos globales 0..N-1,
 *     y modo=1 para tomar control manual. Mandar menos sigue funcionando:
 *     mueve los primeros brazos y deja el resto en busqueda.
 *   H\n   -> todos a HOME
 *   X\n   -> libera todos los servos (dejan de forzar)
 *   ?\n   -> estado
 *
 * MODO PRUEBA (lo usa emparejar_camaras.py)
 *   Emparejar camaras con brazos hay que rehacerlo en CADA arranque, porque
 *   los indices de OpenCV se reordenan. Obligar a cambiar de sketch para eso
 *   seria insostenible, asi que este firmware tambien entiende el subconjunto
 *   del protocolo del calibrador:
 *
 *   PING\n            -> responde y CONGELA el movimiento autonomo
 *   SCAN\n            -> direcciones I2C encontradas
 *   M <placa> <ch> <a>-> mueve un solo servo a ese angulo FISICO, con rampa
 *   R <placa> <ch>    -> libera ese canal
 *   RA\n              -> libera todos
 *   RUN\n             -> vuelve a la operacion normal
 *
 *   Del modo prueba se sale solo tras 5 s sin recibir nada, asi que si el
 *   script se cae o cierras el puerto, el sistema se reanima por su cuenta.
 *
 * Si no llega nada por serial en 3 segundos, vuelve solo al modo de
 * busqueda. Ese failsafe ya estaba en la v3 y se conserva.
 * ---------------------------------------------------------------
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "config_brazos.h"

#define NUM_PLACAS 3

Adafruit_PWMServoDriver pwm[NUM_PLACAS] = {
  Adafruit_PWMServoDriver(0x40),
  Adafruit_PWMServoDriver(0x41),
  Adafruit_PWMServoDriver(0x42)
};

// --- estado, siempre en angulos LOGICOS ---
float pos[TOTAL_SERVOS];
float targetPos[TOTAL_SERVOS];
float t[TOTAL_SERVOS];          // fase propia de cada servo en el ruido

unsigned long ultimoPulsoSerial = 0;
bool modoManual = false;
bool liberados = false;
bool modoPrueba = false;      // congelado, obedeciendo comandos servo a servo
float tVel = 0;

const unsigned long TIMEOUT_MANUAL = 3000;   // ms sin serial -> vuelve a buscar
const unsigned long TIMEOUT_PRUEBA = 5000;   // ms sin serial -> sale de prueba

// Que tanto del recorrido seguro usa la busqueda autonoma (0..1).
// 1.0 llegaria justo a los topes calibrados; 0.6 deja margen y se ve
// menos frenetico. Es el equivalente a los MIN_H/MAX_H estrechos de la v3,
// pero relativo al HOME real de cada servo.
const float AMPLITUD_BUSQUEDA = 0.60;

// Suavizado de la interpolacion global
const float SUAVE_MANUAL = 0.08;
const float SUAVE_BUSQUEDA_BASE = 0.01;

// --- buffer de recepcion ---
const uint8_t LARGO_BUFFER = 200;
char buffer[LARGO_BUFFER];
uint8_t largo = 0;


// ---------------------------------------------------------------
// Ruido 1D suave (igual que en la v3)
// ---------------------------------------------------------------
float noise1D(float x) {
  int x0 = (int)x;
  float f = x - x0;
  float g0 = ((x0 * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483647.0;
  float g1 = (((x0 + 1) * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483647.0;
  return g0 + (3 * f * f - 2 * f * f * f) * (g1 - g0);
}


// ---------------------------------------------------------------
// Escritura: el unico lugar que toca el hardware
// ---------------------------------------------------------------
void escribirServo(uint8_t i) {
  // pos[] es logico; zonaSegura recorta y anguloFisico invierte si toca
  int16_t fisico = anguloSeguroFisico(i, (int16_t)pos[i]);
  uint16_t ticks = map(fisico, 0, 180, SERVOMIN, SERVOMAX);
  pwm[SERVO_PLACA[i]].setPWM(SERVO_CANAL[i], 0, ticks);
}

void actualizarServos() {
  for (uint8_t i = 0; i < TOTAL_SERVOS; i++) escribirServo(i);
}

void liberarTodo() {
  for (uint8_t i = 0; i < TOTAL_SERVOS; i++)
    pwm[SERVO_PLACA[i]].setPWM(SERVO_CANAL[i], 0, 0);
  liberados = true;
}

void irAHome() {
  for (uint8_t i = 0; i < TOTAL_SERVOS; i++) {
    pos[i] = SERVO_HOME[i];
    targetPos[i] = SERVO_HOME[i];
  }
  liberados = false;
  actualizarServos();
}


// ---------------------------------------------------------------
// Modo prueba: control servo a servo (para emparejar_camaras.py)
// ---------------------------------------------------------------
int8_t indiceDe(uint8_t placa, uint8_t canal) {
  for (uint8_t i = 0; i < TOTAL_SERVOS; i++)
    if (SERVO_PLACA[i] == placa && SERVO_CANAL[i] == canal) return (int8_t)i;
  return -1;
}

void escribirFisico(uint8_t i, int16_t fisico) {
  pwm[SERVO_PLACA[i]].setPWM(SERVO_CANAL[i], 0,
                             map(fisico, 0, 180, SERVOMIN, SERVOMAX));
}

// Mueve UN servo a un angulo FISICO, con rampa suave para que la camara
// alcance a ver el movimiento. Se recorta a la zona segura calibrada,
// traducida al espacio fisico (si el servo esta invertido, los extremos
// se cruzan, por eso el min/max de la pareja).
void comandoM(uint8_t placa, uint8_t canal, int16_t destino) {
  int8_t i = indiceDe(placa, canal);
  if (i < 0) { Serial.println(F("ERR canal")); return; }

  int16_t fa = anguloFisico(i, SERVO_MIN[i]);
  int16_t fb = anguloFisico(i, SERVO_MAX[i]);
  int16_t lo = min(fa, fb), hi = max(fa, fb);
  destino = constrain(destino, lo, hi);

  int16_t desde = constrain(anguloFisico(i, (int16_t)pos[i]), lo, hi);
  int8_t paso = (destino >= desde) ? 1 : -1;
  for (int16_t a = desde; a != destino; a += paso) {
    escribirFisico(i, a);
    delay(12);
  }
  escribirFisico(i, destino);

  // dejamos el estado logico coherente para no dar un salto al salir de prueba
  int16_t logico = SERVO_INVERTIDO[i] ? (180 - destino) : destino;
  pos[i] = logico;
  targetPos[i] = logico;

  Serial.print(F("OK M "));
  Serial.print(placa); Serial.print(' ');
  Serial.print(canal); Serial.print(' ');
  Serial.println(destino);
}

void escanearI2C() {
  Serial.print(F("OK SCAN "));
  bool alguna = false;
  for (uint8_t dir = 0x40; dir <= 0x7F; dir++) {
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) {
      if (alguna) Serial.print(',');
      Serial.print(F("0x")); Serial.print(dir, HEX);
      alguna = true;
    }
  }
  if (!alguna) Serial.print(F("ninguna"));
  Serial.println();
}


// ---------------------------------------------------------------
// Parseo del comando $ (sin String)
// ---------------------------------------------------------------
void procesarTrama(char *datos) {
  float valores[TOTAL_SERVOS];
  uint8_t n = 0;
  int modo = 0;

  char *tok = strtok(datos, ",");
  while (tok != NULL) {
    char *siguiente = strtok(NULL, ",");
    if (siguiente == NULL) {
      modo = atoi(tok);          // el ultimo campo es el modo
    } else if (n < TOTAL_SERVOS) {
      valores[n++] = atof(tok);
    }
    tok = siguiente;
  }

  if (n == 0) return;

  if (modo == 1) {
    modoManual = true;
    liberados = false;
    ultimoPulsoSerial = millis();
    // Solo se sobreescriben los servos que vinieron en la trama.
    // Mandar menos valores mueve los primeros brazos y deja el resto buscando.
    for (uint8_t i = 0; i < n; i++) {
      targetPos[i] = zonaSegura(i, (int16_t)valores[i]);
    }
  }
}

void procesarSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (largo == 0) continue;
      buffer[largo] = '\0';

      ultimoPulsoSerial = millis();

      if (buffer[0] == '$') {
        modoPrueba = false;              // una trama normal reanuda todo
        procesarTrama(buffer + 1);
      } else if (strcmp(buffer, "PING") == 0) {
        modoPrueba = true;               // congela el movimiento autonomo
        modoManual = false;
        liberados = false;
        Serial.println(F("OK MILOJOS v5 modo prueba"));
      } else if (strcmp(buffer, "SCAN") == 0) {
        escanearI2C();
      } else if (strcmp(buffer, "RUN") == 0) {
        modoPrueba = false;
        Serial.println(F("OK RUN"));
      } else if (strcmp(buffer, "RA") == 0) {
        liberarTodo();
        Serial.println(F("OK RA"));
      } else if (buffer[0] == 'M' && buffer[1] == ' ') {
        int p, c, a;
        if (sscanf(buffer + 1, "%d %d %d", &p, &c, &a) == 3 &&
            p >= 0 && p < NUM_PLACAS && c >= 0 && c < 16) {
          modoPrueba = true;
          liberados = false;
          comandoM((uint8_t)p, (uint8_t)c, (int16_t)a);
        } else {
          Serial.println(F("ERR M"));
        }
      } else if (buffer[0] == 'R' && buffer[1] == ' ') {
        int p, c;
        if (sscanf(buffer + 1, "%d %d", &p, &c) == 2 &&
            p >= 0 && p < NUM_PLACAS && c >= 0 && c < 16) {
          pwm[p].setPWM(c, 0, 0);
          Serial.print(F("OK R ")); Serial.print(p);
          Serial.print(' '); Serial.println(c);
        } else {
          Serial.println(F("ERR R"));
        }
      } else if (buffer[0] == 'H' || buffer[0] == 'h') {
        modoPrueba = false;
        irAHome();
        Serial.println(F("OK HOME"));
      } else if (buffer[0] == 'X' || buffer[0] == 'x') {
        liberarTodo();
        Serial.println(F("OK LIBERADOS"));
      } else if (buffer[0] == '?') {
        Serial.print(F("OK v4 servos="));
        Serial.print(TOTAL_SERVOS);
        Serial.print(F(" modo="));
        if (modoPrueba)      Serial.println(F("prueba"));
        else if (modoManual) Serial.println(F("manual"));
        else                 Serial.println(F("busqueda"));
      }
      largo = 0;
    } else if (largo < LARGO_BUFFER - 1) {
      buffer[largo++] = c;
    } else {
      largo = 0;   // trama demasiado larga: se descarta
    }
  }
}


// ---------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  Wire.begin();

  for (uint8_t p = 0; p < NUM_PLACAS; p++) {
    pwm[p].begin();
    pwm[p].setPWMFreq(50);
  }

  for (uint8_t i = 0; i < TOTAL_SERVOS; i++) t[i] = i * 100.0;

  irAHome();          // arranca en la postura calibrada, no en 90 a ciegas
  delay(300);

  Serial.println(F("MIL OJOS v4 listo"));
}


void loop() {
  unsigned long ahora = millis();

  procesarSerial();

  // Failsafe: sin serial por 3 s, vuelve a la busqueda suave
  if (modoManual && ahora - ultimoPulsoSerial > TIMEOUT_MANUAL) {
    modoManual = false;
  }

  // Y si el script de emparejamiento se cayo o cerro el puerto, el sistema
  // sale solo del modo prueba en vez de quedarse congelado para siempre.
  if (modoPrueba && ahora - ultimoPulsoSerial > TIMEOUT_PRUEBA) {
    modoPrueba = false;
  }

  // En modo prueba los servos los manda el script, uno por uno
  if (modoPrueba) {
    delay(5);
    return;
  }

  float suavizado;

  if (modoManual) {
    suavizado = SUAVE_MANUAL;
  } else {
    // --- busqueda autonoma ---
    tVel += 0.004;
    float dt = map(pow(noise1D(tVel), 1.5) * 1000, 0, 1000, 2, 15) / 1000.0;

    for (uint8_t i = 0; i < TOTAL_SERVOS; i++) {
      t[i] += dt * (1.0 + (i * 0.015));

      // recorrido disponible a cada lado del HOME, ya calibrado
      int16_t margen = min(SERVO_HOME[i] - SERVO_MIN[i],
                           SERVO_MAX[i] - SERVO_HOME[i]);
      float amplitud = margen * AMPLITUD_BUSQUEDA;
      float n = noise1D(t[i]) * 2.0 - 1.0;        // -1 .. 1
      targetPos[i] = SERVO_HOME[i] + n * amplitud;
    }
    suavizado = SUAVE_BUSQUEDA_BASE;
  }

  if (!liberados) {
    for (uint8_t i = 0; i < TOTAL_SERVOS; i++) {
      targetPos[i] = zonaSegura(i, (int16_t)targetPos[i]);
      pos[i] += (targetPos[i] - pos[i]) * suavizado;
    }
    actualizarServos();
  }

  delay(5);
}
