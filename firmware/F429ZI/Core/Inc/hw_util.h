/*
 * hw_util.h - Utilidades de bajo nivel compartidas por los módulos del
 * instrumento (relojes de timers, caché de datos, números sin printf de float).
 */
#ifndef HW_UTIL_H
#define HW_UTIL_H

#include "placa.h"
#include <stdint.h>
#include <stddef.h>

/* Prioridades NVIC usadas por el instrumento (0 = más alta). */
#define PRIO_DAC_DMA     1u
#define PRIO_ADC_DMA     2u
#define PRIO_FRECUENC    3u

/* Tope de iteraciones al esperar que un stream de DMA se apague (EN = 0).
 * Evita colgar el lazo principal si el hardware no responde. */
#define ESPERA_DMA_ITER  100000u

/* Frecuencia del reloj de los timers de APB1 (TIM2..7, 12..14) */
uint32_t clk_tim_apb1(void);
/* Frecuencia del reloj de los timers de APB2 (TIM1, TIM8..11) */
uint32_t clk_tim_apb2(void);

/* Mantenimiento de caché para buffers usados por DMA. No hacen nada si la
 * D-Cache está desactivada en CubeMX. */
void cache_limpiar(const void *p, size_t n);     /* CPU -> memoria (antes de que lea el DMA) */
void cache_invalidar(const void *p, size_t n);   /* memoria -> CPU (después de que escribe el DMA) */

/* Conversión de texto a número sin depender de strtod/printf con float
 * (CubeIDE usa newlib-nano, que por defecto no formatea floats). */
int    leer_double(const char *s, double *v);
/* Escribe v con 'dec' decimales en buf; devuelve la cantidad de caracteres. */
int    fmt_double(char *buf, size_t n, double v, int dec);

#endif
