/*
 * ad9833.c - Control del módulo AD9833 (DDS) + MCP41010 (amplitud)
 * Ver ad9833.h para la conexión y las modulaciones.
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
#define AD_FSELECT  (1u << 11)   /* la salida usa FREQ1 */
#define AD_PSELECT  (1u << 10)   /* la salida usa PHASE1 */
#define AD_RESET    (1u << 8)
#define AD_SLEEP1   (1u << 7)    /* reloj interno apagado */
#define AD_SLEEP12  (1u << 6)    /* DAC apagado */
#define AD_OPBITEN  (1u << 5)    /* salida = MSB (cuadrada) */
#define AD_DIV2     (1u << 3)    /* cuadrada a la frecuencia pedida (sin él, a la mitad) */
#define AD_MODE     (1u << 1)    /* triangular */
#define AD_FREQ0    0x4000u
#define AD_FREQ1    0x8000u
#define AD_PHASE0   0xC000u
#define AD_PHASE1   0xE000u

#define DOS_28      268435456.0  /* 2^28 */
#define PI2         6.283185307179586

/* Estado */
static double     mclk = DDS_MCLK_HZ;
static double     f_base = 1000.0;       /* frecuencia pedida (FREQ0) */
static double     fase_base = 0.0;       /* grados (PHASE0) */
static dds_forma_t forma = DDS_SENO;
static int        habilitado = 0;
static uint8_t    amp_base = 0;
static uint16_t   sel = 0;               /* bits FSELECT / PSELECT en uso */

static dds_mod_t  mod = DDS_MOD_NO;
static double     mod_a, mod_b, mod_c;
static double     t_mod;                 /* tiempo dentro de la modulación (s) */
static double     t_ultimo_cambio;       /* para no escribir más seguido de lo necesario */
static uint32_t   cyc_ultimo;
static int        rafaga_encendida;

/* ------------------------------------------------------------------------ */
/* SPI por software                                                          */
/* ------------------------------------------------------------------------ */
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

static void pote(uint8_t paso)
{
  BAJO(CS_PUERTO, CS_PIN);
  espera();
  enviar_bits(0x11u, 8u);          /* escribir el dato del potenciómetro 0 */
  enviar_bits(paso, 8u);
  ALTO(CS_PUERTO, CS_PIN);
  espera();
}

/* ------------------------------------------------------------------------ */
/* Registros                                                                 */
/* ------------------------------------------------------------------------ */
static double f_max(void) { return mclk / 2.0; }

static uint32_t reg_frec(double f)
{
  if (!(f >= 0.0)) f = 0.0;               /* también NaN */
  if (f > f_max()) f = f_max();
  double r = f * DOS_28 / mclk;
  if (r > 268435455.0) r = 268435455.0;
  return (uint32_t)lround(r);
}

static void escribir_frec(int registro, double f)
{
  uint32_t r = reg_frec(f);
  uint16_t dir = registro ? AD_FREQ1 : AD_FREQ0;
  ad_palabra((uint16_t)(dir | (r & 0x3FFFu)));            /* B28: primero los 14 de abajo */
  ad_palabra((uint16_t)(dir | ((r >> 14) & 0x3FFFu)));    /* ...y recién acá se aplica */
}

static uint16_t reg_fase(double grados)
{
  double g = fmod(grados, 360.0);
  if (g < 0.0) g += 360.0;
  return (uint16_t)(lround(g * 4096.0 / 360.0) & 0x0FFF);
}

static void escribir_fase(int registro, double grados)
{
  ad_palabra((uint16_t)((registro ? AD_PHASE1 : AD_PHASE0) | reg_fase(grados)));
}

static uint16_t bits_forma(void)
{
  switch (forma) {
    case DDS_TRIANGULAR:     return AD_MODE;
    case DDS_CUADRADA:       return AD_OPBITEN | AD_DIV2;
    case DDS_CUADRADA_MITAD: return AD_OPBITEN;
    default:                 return 0u;
  }
}

/* Escribe el registro de control según el estado (encendido, forma, selección) */
static void escribir_control(int apagado_por_rafaga)
{
  if (!habilitado) {
    ad_palabra(AD_B28 | AD_RESET | AD_SLEEP1 | AD_SLEEP12);
  } else if (apagado_por_rafaga) {
    ad_palabra((uint16_t)(AD_B28 | AD_RESET | bits_forma()));   /* salida quieta en el medio */
  } else {
    ad_palabra((uint16_t)(AD_B28 | bits_forma() | sel));
  }
}

static uint32_t ciclos(void) { return DWT->CYCCNT; }

static void reiniciar_tiempo(void)
{
  t_mod = 0.0;
  t_ultimo_cambio = -1.0;
  cyc_ultimo = ciclos();
}

/* ------------------------------------------------------------------------ */
/* API                                                                       */
/* ------------------------------------------------------------------------ */
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

  /* Contador de ciclos del núcleo, para los tiempos de las modulaciones */
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  *(volatile uint32_t *)0xE0001FB0u = 0xC5ACCE55u;   /* desbloqueo (lo pide el M7; en el M4 no molesta) */
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

  /* Arranca apagado: si el módulo no está conectado, no pasa nada */
  habilitado = 0;
  mod = DDS_MOD_NO;
  sel = 0;
  escribir_control(0);
  dds_amplitud(0);
}

double dds_configurar(double frec, dds_forma_t f, int hab)
{
  if (!(frec >= 0.0)) frec = 0.0;
  if (frec > f_max()) frec = f_max();
  f_base = frec;
  forma = (f <= DDS_CUADRADA_MITAD) ? f : DDS_SENO;
  habilitado = hab != 0;

  ad_palabra(AD_B28 | AD_RESET);                 /* fase a cero mientras se carga */
  escribir_frec(0, f_base);
  escribir_fase(0, fase_base);
  if (mod == DDS_MOD_FSK) escribir_frec(1, mod_a);
  if (mod == DDS_MOD_PSK) escribir_fase(1, mod_a);
  sel = 0;
  rafaga_encendida = 1;
  reiniciar_tiempo();
  escribir_control(0);
  return (double)reg_frec(f_base) * mclk / DOS_28;
}

void dds_amplitud(uint8_t paso)
{
  amp_base = paso;
  pote(paso);
}

double dds_fase(double grados)
{
  fase_base = grados;
  escribir_fase(0, fase_base);
  return (double)reg_fase(grados) * 360.0 / 4096.0;
}

double dds_reloj(double hz)
{
  if (hz >= 20e6 && hz <= 30e6) mclk = hz;       /* el cristal no puede estar tan lejos */
  return mclk;
}

double dds_reloj_actual(void) { return mclk; }

int dds_modulacion(dds_mod_t tipo, double a, double b, double c)
{
  switch (tipo) {
    case DDS_MOD_BARRIDO_LIN:
    case DDS_MOD_BARRIDO_LOG:
      if (!(a > 0.0 && b > 0.0 && a <= f_max() && b <= f_max() && c >= 0.05 && c <= 1000.0)) return 0;
      break;
    case DDS_MOD_FSK:
      if (!(a >= 0.0 && a <= f_max() && b >= 0.1 && b <= 5000.0)) return 0;
      break;
    case DDS_MOD_PSK:
      if (!(b >= 0.1 && b <= 5000.0) || !isfinite(a)) return 0;
      break;
    case DDS_MOD_RAFAGA:
      if (!(a >= 1.0 && a <= 1e6 && b >= 0.001 && b <= 100.0)) return 0;
      break;
    case DDS_MOD_AM:
      if (!(a >= 0.0 && a <= 1.0 && b >= 0.01 && b <= 200.0)) return 0;
      break;
    case DDS_MOD_NO:
      break;
    default:
      return 0;
  }
  mod = tipo;
  mod_a = a;
  mod_b = b;
  mod_c = c;
  /* Volver al estado de base y preparar los registros auxiliares */
  if (tipo == DDS_MOD_FSK) escribir_frec(1, a);
  if (tipo == DDS_MOD_PSK) escribir_fase(1, a);
  escribir_frec(0, f_base);
  sel = 0;
  rafaga_encendida = 1;
  pote(amp_base);
  reiniciar_tiempo();
  escribir_control(0);
  return 1;
}

void dds_lazo(void)
{
  if (mod == DDS_MOD_NO || !habilitado) return;
  uint32_t ahora = ciclos();
  double dt = (double)(uint32_t)(ahora - cyc_ultimo) / (double)SystemCoreClock;
  cyc_ultimo = ahora;
  t_mod += dt;

  switch (mod) {
    case DDS_MOD_BARRIDO_LIN:
    case DDS_MOD_BARRIDO_LOG: {
      if (t_mod >= mod_c) t_mod = fmod(t_mod, mod_c);
      if (t_ultimo_cambio >= 0.0 && fabs(t_mod - t_ultimo_cambio) < 0.0005) return;   /* cada 0,5 ms */
      t_ultimo_cambio = t_mod;
      double x = t_mod / mod_c;
      double f = (mod == DDS_MOD_BARRIDO_LIN) ? mod_a + (mod_b - mod_a) * x
                                             : mod_a * pow(mod_b / mod_a, x);
      escribir_frec(0, f);
      break;
    }
    case DDS_MOD_FSK:
    case DDS_MOD_PSK: {
      double simbolo = 1.0 / mod_b;
      if (t_mod < simbolo) return;
      t_mod = fmod(t_mod, simbolo);
      sel ^= (mod == DDS_MOD_FSK) ? AD_FSELECT : AD_PSELECT;
      escribir_control(0);
      break;
    }
    case DDS_MOD_RAFAGA: {
      if (t_mod >= mod_b) t_mod = fmod(t_mod, mod_b);
      double t_on = mod_a / (f_base > 0.0 ? f_base : 1.0);
      int encendida = t_mod < t_on;
      if (encendida != rafaga_encendida) {
        rafaga_encendida = encendida;
        escribir_control(!encendida);    /* RESET: la próxima ráfaga arranca en fase 0 */
      }
      break;
    }
    case DDS_MOD_AM: {
      if (t_mod >= 1000.0) t_mod = fmod(t_mod, 1.0 / mod_b);
      if (t_ultimo_cambio >= 0.0 && fabs(t_mod - t_ultimo_cambio) < 0.0002) return;   /* cada 0,2 ms */
      t_ultimo_cambio = t_mod;
      double g = (1.0 + mod_a * sin(PI2 * mod_b * t_mod)) / (1.0 + mod_a);
      double p = (double)amp_base * g;
      if (p < 0.0) p = 0.0;
      if (p > 255.0) p = 255.0;
      pote((uint8_t)lround(p));
      break;
    }
    default:
      break;
  }
}
