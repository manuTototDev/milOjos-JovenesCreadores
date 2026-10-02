// GENERADO POR python/generar_header.py - NO EDITAR A MANO
// 2026-10-01T19:10:42
// AVISO: brazos sin calibrar (valores por defecto): [8]
#pragma once

#define NUM_BRAZOS 9
#define SERVOS_POR_BRAZO 3
#define TOTAL_SERVOS (NUM_BRAZOS * SERVOS_POR_BRAZO)

#define SERVOMIN 150
#define SERVOMAX 600

// indice global = brazo * SERVOS_POR_BRAZO + slot
// placa 0 -> 0x40 (brazos 0-2), placa 1 -> 0x41 (brazos 3-5), placa 2 -> 0x42 (brazos 6-8)

const uint8_t SERVO_PLACA[TOTAL_SERVOS] = {
  0, 0, 0,  // brazo 0
  0, 0, 0,  // brazo 1
  0, 0, 0,  // brazo 2
  1, 1, 1,  // brazo 3
  1, 1, 1,  // brazo 4
  1, 1, 1,  // brazo 5
  2, 2, 2,  // brazo 6
  2, 2, 2,  // brazo 7
  2, 2, 2,  // brazo 8
};

const uint8_t SERVO_CANAL[TOTAL_SERVOS] = {
  0, 1, 2,  // brazo 0
  3, 4, 5,  // brazo 1
  6, 7, 8,  // brazo 2
  0, 1, 2,  // brazo 3
  3, 4, 5,  // brazo 4
  6, 7, 8,  // brazo 5
  0, 1, 2,  // brazo 6
  3, 4, 5,  // brazo 7
  6, 7, 8,  // brazo 8
};

const int16_t SERVO_MIN[TOTAL_SERVOS] = {
  41, 15, 0,  // brazo 0
  48, 30, 31,  // brazo 1
  60, 30, 0,  // brazo 2
  30, 10, 20,  // brazo 3
  30, 30, 30,  // brazo 4
  30, 30, 30,  // brazo 5
  30, 30, 30,  // brazo 6
  30, 30, 30,  // brazo 7
  30, 30, 30,  // brazo 8
};

const int16_t SERVO_MAX[TOTAL_SERVOS] = {
  130, 90, 110,  // brazo 0
  117, 150, 120,  // brazo 1
  140, 150, 150,  // brazo 2
  150, 129, 116,  // brazo 3
  150, 150, 150,  // brazo 4
  150, 150, 150,  // brazo 5
  150, 150, 150,  // brazo 6
  150, 150, 150,  // brazo 7
  150, 150, 150,  // brazo 8
};

const int16_t SERVO_HOME[TOTAL_SERVOS] = {
  86, 54, 59,  // brazo 0
  89, 45, 90,  // brazo 1
  92, 90, 90,  // brazo 2
  90, 27, 90,  // brazo 3
  90, 90, 90,  // brazo 4
  90, 90, 90,  // brazo 5
  90, 90, 90,  // brazo 6
  90, 90, 90,  // brazo 7
  90, 90, 90,  // brazo 8
};

const bool SERVO_INVERTIDO[TOTAL_SERVOS] = {
  false, false, false,  // brazo 0
  false, false, false,  // brazo 1
  false, false, false,  // brazo 2
  false, false, false,  // brazo 3
  false, false, false,  // brazo 4
  false, false, false,  // brazo 5
  false, false, false,  // brazo 6
  false, false, false,  // brazo 7
  false, false, false,  // brazo 8
};

// Mapa de articulaciones (solo referencia, no ocupa RAM):
//   brazo 0 (indices 0-2): base, hombro, codo
//   brazo 1 (indices 3-5): base, hombro, codo
//   brazo 2 (indices 6-8): base, hombro, codo
//   brazo 3 (indices 9-11): base, hombro, codo
//   brazo 4 (indices 12-14): base, hombro, codo
//   brazo 5 (indices 15-17): base, hombro, codo
//   brazo 6 (indices 18-20): base, hombro, codo
//   brazo 7 (indices 21-23): base, hombro, codo
//   brazo 8 (indices 24-26): n/a, n/a, n/a

// ---------------------------------------------------------------
// CONVENCION DE SENTIDO (angulos LOGICOS, iguales para los 9 brazos)
//   slot 0 (base): angulo bajo = izquierda, angulo alto = derecha
//   slot 1 (hombro): angulo bajo = atras, angulo alto = adelante
//   slot 2 (codo): angulo bajo = atras, angulo alto = adelante
// Si un servo quedo atornillado al reves, SERVO_INVERTIDO[i] es true
// y anguloFisico() le da la vuelta. Trabaja SIEMPRE en logicos.
// ---------------------------------------------------------------

// Recorta un angulo logico a la zona segura del servo global i
inline int16_t zonaSegura(uint8_t i, int16_t ang) {
  if (ang < SERVO_MIN[i]) return SERVO_MIN[i];
  if (ang > SERVO_MAX[i]) return SERVO_MAX[i];
  return ang;
}

// Convierte angulo LOGICO -> angulo FISICO que se manda al servo
inline int16_t anguloFisico(uint8_t i, int16_t ang) {
  return SERVO_INVERTIDO[i] ? (180 - ang) : ang;
}

// Lo normal: recortar a zona segura y traducir de un golpe
inline int16_t anguloSeguroFisico(uint8_t i, int16_t ang) {
  return anguloFisico(i, zonaSegura(i, ang));
}
