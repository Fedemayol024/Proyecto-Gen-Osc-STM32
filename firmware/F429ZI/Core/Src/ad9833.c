/*
 * ad9833.c - Control del módulo AD9833 (DDS) + MCP41010 (amplitud)
 * Ver ad9833.h para la conexión.
 */
#include "ad9833.h"
#include "placa.h"
#include <math.h>

/* Pines (puerto, número) */
#define CLK_PUERTO  GPIOC
#define CLK_PIN     10u
#define DAT_PUERTO  GPIOC
#define DAT_PIN     12u
#define FSY_PUERTO  GPIOD
#define FSY_PIN     2u
#define CS_PUERTO   GPIOG
#define CS_PIN      2u

#define ALTO(p, n)  ((p)->BSRR = (1u << (n)))
#define BAJO(p, n)  ((p)->BSRR = (1u << ((n) + 16u)))

/* Registro de control del AD9833 */
#define AD_B28      (1u << 13)   /* escribir los 28 bits de frecuencia en dos palabras */
#define AD_RESET    (1u << 8)
#define AD_SLEEP1   (1u << 7)    /* reloj interno apagado */
#define AD_SLEEP12  (1u << 6)    /* DAC apagado */
#define AD_OPBITEN  (1u << 5)    /* salida = MSB (cuadrada) */
#define AD_DIV2     (1u << 3)    /* cuadrada a la frecuencia pedida (no a la mitad) */
#define AD_MODE     (1u << 1)    /* triangular */
#define AD_FREQ0    0x4000u
#define AD_PHASE0   0xC000u

static void espera(void)
{
  /* ~100 ns a 216 MHz: el bit-bang queda en ~2 MHz, sobra para los dos chips
   * (AD9833 hasta 40 MHz, MCP41010 hasta 10 MHz) aun con cables Dupont. */
  for (volatile uint32_t i = 0; i < 6u; i++) { }
}

static void salida_gpio(GPIO_TypeDef *p, uint32_t n)
{
  p->MODER   = (p->MODER & ~(3u << (2u * n))) | (1u << (2u * n));   /* salida */
  p->OTYPER &= ~(1u << n);                                          /* push-pull */
  p->OSPEEDR = (p->OSPEEDR & ~(3u << (2u * n))) | (1u << (2u * n)); /* velocidad media */
  p->PUPDR  &= ~(3u << (2u * n));
}

static void enviar_bits(uint32_t dato, uint32_t bits)
{
  for (uint32_t i = 0; i < bits; i++) {
    if (dato & (1u << (bits - 1u - i))) ALTO(DAT_PUERTO, DAT_PIN);
    else BAJO(DAT_PUERTO, DAT_PIN);
    espera();
    BAJO(CLK_PUERTO, CLK_PIN);    /* el AD9833 lee acá */
    espera();
    ALTO(CLK_PUERTO, CLK_PIN);    /* el MCP41010 lee acá */
    espera();
  }
}

static void ad_palabra(uint16_t w)
{
  BAJO(FSY_PUERTO, FSY_PIN);
  espera();
  enviar_bits(w, 16u);
  ALTO(FSY_PUERTO, FSY_PIN);
  espera();
}

void dds_iniciar(void)
{
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN | RCC_AHB1ENR_GPIODEN | RCC_AHB1ENR_GPIOGEN;
  (void)RCC->AHB1ENR;
  ALTO(CLK_PUERTO, CLK_PIN);      /* reposo: reloj alto, selecciones en alto */
  ALTO(FSY_PUERTO, FSY_PIN);
  ALTO(CS_PUERTO, CS_PIN);
  BAJO(DAT_PUERTO, DAT_PIN);
  salida_gpio(CLK_PUERTO, CLK_PIN);
  salida_gpio(DAT_PUERTO, DAT_PIN);
  salida_gpio(FSY_PUERTO, FSY_PIN);
  salida_gpio(CS_PUERTO, CS_PIN);

  /* Arranca apagado: si el módulo no está conectado, no pasa nada */
  ad_palabra(AD_B28 | AD_RESET | AD_SLEEP1 | AD_SLEEP12);
  dds_amplitud(0);
}

double dds_configurar(double frec, dds_forma_t forma, int habilitado)
{
  if (!(frec >= 0.0)) frec = 0.0;               /* también NaN */
  if (frec > DDS_F_MAX) frec = DDS_F_MAX;
  uint32_t reg = (uint32_t)lround(frec * 268435456.0 / DDS_MCLK_HZ);   /* 2^28 */
  if (reg > 0x0FFFFFFFu) reg = 0x0FFFFFFFu;

  uint16_t control = AD_B28;
  if (forma == DDS_TRIANGULAR) control |= AD_MODE;
  else if (forma == DDS_CUADRADA) control |= AD_OPBITEN | AD_DIV2;

  ad_palabra(AD_B28 | AD_RESET);                 /* fase a cero mientras se carga */
  ad_palabra((uint16_t)(AD_FREQ0 | (reg & 0x3FFFu)));
  ad_palabra((uint16_t)(AD_FREQ0 | ((reg >> 14) & 0x3FFFu)));
  ad_palabra(AD_PHASE0);
  if (habilitado) ad_palabra(control);
  else ad_palabra(AD_B28 | AD_RESET | AD_SLEEP1 | AD_SLEEP12);
  return (double)reg * DDS_MCLK_HZ / 268435456.0;
}

void dds_amplitud(uint8_t paso)
{
  BAJO(CS_PUERTO, CS_PIN);
  espera();
  enviar_bits(0x11u, 8u);          /* escribir el dato del potenciómetro 0 */
  enviar_bits(paso, 8u);
  ALTO(CS_PUERTO, CS_PIN);
  espera();
}
