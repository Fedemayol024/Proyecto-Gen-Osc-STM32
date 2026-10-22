/*
 * frecuencimetro.h - Frecuencímetro digital en PA0 (D32), señal lógica 0-3,3 V
 *
 * Dos métodos, que se eligen solos según la frecuencia:
 *  - Conteo (frecuencias altas): TIM2 cuenta flancos por su entrada ETR
 *    durante un tiempo de compuerta exacto medido por TIM5.
 *  - Recíproco (frecuencias bajas): TIM2 mide con captura de entrada el
 *    tiempo entre flancos con resolución de 1/108 MHz.
 */
#ifndef FRECUENCIMETRO_H
#define FRECUENCIMETRO_H

#include <stdint.h>

typedef struct {
  double   frecuencia;   /* Hz (0 si no hubo flancos suficientes) */
  uint32_t flancos;      /* flancos contados */
  uint32_t compuerta_ms;
  char     metodo;       /* 'C' conteo, 'R' recíproco */
} fcnt_resultado_t;

void fcnt_iniciar(void);
/* Comienza a medir. compuerta_ms entre 10 y 10000. continuo: repite solo. */
void fcnt_medir(uint32_t compuerta_ms, int continuo);
void fcnt_detener(void);
/* Devuelve 1 si hay un resultado nuevo */
int  fcnt_resultado(fcnt_resultado_t *r);

#endif
