/*
 * osciloscopio.h - Osciloscopio de 2 canales (CH1 = PA3/A0, CH2 = PC0/A1)
 *
 * ADC1 y ADC2 en modo dual simultáneo: las dos entradas se muestrean en el
 * mismo instante, disparadas por TIM8 a la frecuencia pedida (hasta
 * ~1,6 MS/s). El DMA guarda pares de muestras (CH2 << 16 | CH1) en un
 * buffer; después se busca el disparo (trigger) en ese buffer y se entrega
 * la ventana pedida.
 */
#ifndef OSCILOSCOPIO_H
#define OSCILOSCOPIO_H

#include <stdint.h>
#include "placa.h"

#define OSC_MAX_MUESTRAS  PLACA_OSC_MAX_MUESTRAS   /* tamaño del buffer de captura (pares) */
#define OSC_MAX_VENTANA   8192u      /* puntos máximos por canal enviados a la PC */

typedef enum { OSC_FLANCO_SUBE = 0, OSC_FLANCO_BAJA = 1 } osc_flanco_t;

typedef struct {
  uint32_t n;          /* puntos de la ventana */
  uint32_t pre;        /* puntos antes del disparo */
  double   fs;         /* muestras por segundo pedidas */
  int      fuente;     /* 0 = libre (sin disparo), 1 = CH1, 2 = CH2 */
  uint16_t nivel;      /* nivel de disparo (código ADC 0..4095) */
  osc_flanco_t flanco;
  uint16_t hist;       /* histéresis (códigos) */
} osc_param_t;

void     osc_iniciar(void);
double   osc_fs_max(void);

/* Arranca una captura. Devuelve la frecuencia de muestreo real. */
double   osc_capturar(const osc_param_t *p);
void     osc_abortar(void);
/* Cantidad de capturas abortadas por error de DMA desde el arranque */
uint32_t osc_errores(void);

/* 1 cuando hay una ventana lista para enviar */
int      osc_listo(void);
/* Ventana lista: puntero a n palabras (CH2<<16 | CH1). disparado: 1 si se
 * encontró el disparo, 0 si no (modo automático), 2 si la fuente es libre. */
const uint32_t *osc_ventana(uint32_t *n, uint32_t *pre, double *fs, int *disparado);
/* Llamar cuando terminó de enviarse la ventana (libera el buffer) */
void     osc_liberar(void);
int      osc_ocupado(void);

#endif
