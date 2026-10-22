/*
 * generador.h - Generador de señales de 2 canales (DAC1 = PA4, DAC2 = PA5)
 *
 * Funcionamiento: síntesis digital directa (DDS) a frecuencia de muestreo
 * fija (~1 MS/s, TIM6). Cada canal recorre una tabla de 4096 códigos de
 * 12 bits que manda la PC (así la forma de onda puede ser cualquiera y la
 * calibración se resuelve en la PC). El DMA lleva las muestras al DAC en
 * modo dual (los dos canales cambian en el mismo instante) y la CPU calcula
 * medio buffer por vez en la interrupción del DMA, lo que permite modular
 * (AM/FM) y hacer barridos de frecuencia en tiempo real.
 */
#ifndef GENERADOR_H
#define GENERADOR_H

#include <stdint.h>

#define GEN_CANALES     2
#define GEN_TABLA_BITS  12
#define GEN_TABLA_N     (1u << GEN_TABLA_BITS)   /* 4096 puntos por período */

typedef enum { GEN_MOD_NINGUNA = 0, GEN_MOD_AM, GEN_MOD_FM } gen_mod_t;
typedef enum { GEN_BARR_NO = 0, GEN_BARR_LIN, GEN_BARR_LOG } gen_barrido_t;

void     gen_iniciar(void);
double   gen_fs(void);                         /* frecuencia de muestreo real */

/* Escribe una tabla nueva (n = GEN_TABLA_N códigos). Se aplica sin cortes. */
uint16_t *gen_tabla_libre(int canal);          /* buffer donde escribir */
void     gen_tabla_confirmar(int canal);       /* activa la tabla escrita */

/* Frecuencia en Hz (0 = DC con el primer punto de la tabla), fase relativa
 * en grados (se aplica en la próxima sincronización), habilitado y nivel de
 * reposo (código) cuando está deshabilitado. Devuelve la frecuencia real. */
double   gen_configurar(int canal, double frec, double fase_grados, int habilitado, uint16_t reposo);
double   gen_modulacion(int canal, gen_mod_t tipo, double profundidad_o_desvio, double frec_mod,
                        double centro);
void     gen_barrido(int canal, gen_barrido_t modo, double f1, double f2, double tiempo_s);
void     gen_vigilar(void);                    /* llamar seguido desde el lazo principal */
void     gen_sincronizar(void);                /* reinicia las fases de ambos canales */
uint32_t gen_subejecuciones(void);             /* cantidad de veces que el DMA se adelantó */

#endif
