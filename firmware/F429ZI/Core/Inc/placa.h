/*
 * placa.h - Diferencias entre las placas soportadas por el instrumento.
 *
 * El mismo código compila para las dos Nucleo-144; la placa se detecta sola
 * por la definición que pone STM32CubeIDE según el micro del proyecto
 * (STM32F767xx o STM32F429xx). Los pines usados son los mismos en ambas.
 *
 *                      NUCLEO-F767ZI          NUCLEO-F429ZI
 *   Núcleo             Cortex-M7, 216 MHz     Cortex-M4, 168 MHz (por el USB)
 *   Caché de datos     sí                     no
 *   RAM para DMA       512 KB                 192 KB  -> buffer del osciloscopio más chico
 *   Disparo ADC TIM8   EXTSEL = 0111          EXTSEL = 1110
 *   Prescaler timers   RCC->DCKCFGR1          RCC->DCKCFGR
 */
#ifndef PLACA_H
#define PLACA_H

#if defined(STM32F767xx) || defined(STM32F769xx) || defined(STM32F765xx) || \
    defined(STM32F777xx) || defined(STM32F779xx)
  #include "stm32f7xx_hal.h"
  #define PLACA_ID                     "F767"
  #define PLACA_ADC_EXTSEL_TIM8_TRGO   7u        /* 0111 */
  #define PLACA_OSC_MAX_MUESTRAS       32768u    /* 128 KB */
#elif defined(STM32F429xx) || defined(STM32F439xx) || defined(STM32F427xx) || \
      defined(STM32F437xx)
  #include "stm32f4xx_hal.h"
  #define PLACA_ID                     "F429"
  #define PLACA_ADC_EXTSEL_TIM8_TRGO   14u       /* 1110 */
  #define PLACA_OSC_MAX_MUESTRAS       16384u    /* 64 KB: la SRAM es de 192 KB */
#else
  #error "Placa no soportada: el instrumento es para NUCLEO-F767ZI o NUCLEO-F429ZI."
#endif

/* Bit TIMPRE (reloj de los timers): cambia el nombre del registro */
#if defined(RCC_DCKCFGR1_TIMPRE)
  #define PLACA_TIMPRE_ACTIVO()  ((RCC->DCKCFGR1 & RCC_DCKCFGR1_TIMPRE) != 0u)
#elif defined(RCC_DCKCFGR_TIMPRE)
  #define PLACA_TIMPRE_ACTIVO()  ((RCC->DCKCFGR & RCC_DCKCFGR_TIMPRE) != 0u)
#else
  #define PLACA_TIMPRE_ACTIVO()  0
#endif

/* Caché de datos (solo Cortex-M7) */
#if defined(__DCACHE_PRESENT) && (__DCACHE_PRESENT == 1U)
  #define PLACA_TIENE_DCACHE 1
#else
  #define PLACA_TIENE_DCACHE 0
#endif

#endif
