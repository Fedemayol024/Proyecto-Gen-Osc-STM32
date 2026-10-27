/*
 * hw_util.c - Ver hw_util.h
 */
#include "hw_util.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

/* El reloj de un timer es PCLK si el prescaler de APB es 1, y 2*PCLK si no.
 * Si TIMPRE está activo (RCC_DCKCFGR1 en F7, RCC_DCKCFGR en F4), es HCLK cuando el prescaler es 1, 2
 * o 4, y 4*PCLK en los demás casos. */
static uint32_t clk_tim(uint32_t pclk, uint32_t ppre_bits, uint32_t div1_bits, uint32_t div2_bits,
                        uint32_t div4_bits)
{
  int timpre = PLACA_TIMPRE_ACTIVO();
  if (!timpre) {
    return (ppre_bits == div1_bits) ? pclk : 2u * pclk;
  }
  if (ppre_bits == div1_bits || ppre_bits == div2_bits || ppre_bits == div4_bits) {
    return HAL_RCC_GetHCLKFreq();
  }
  return 4u * pclk;
}

uint32_t clk_tim_apb1(void)
{
  return clk_tim(HAL_RCC_GetPCLK1Freq(), RCC->CFGR & RCC_CFGR_PPRE1,
                 RCC_CFGR_PPRE1_DIV1, RCC_CFGR_PPRE1_DIV2, RCC_CFGR_PPRE1_DIV4);
}

uint32_t clk_tim_apb2(void)
{
  return clk_tim(HAL_RCC_GetPCLK2Freq(), RCC->CFGR & RCC_CFGR_PPRE2,
                 RCC_CFGR_PPRE2_DIV1, RCC_CFGR_PPRE2_DIV2, RCC_CFGR_PPRE2_DIV4);
}

#if PLACA_TIENE_DCACHE
static int dcache_activa(void)
{
  return (SCB->CCR & SCB_CCR_DC_Msk) != 0u;
}
#endif

void cache_limpiar(const void *p, size_t n)
{
#if !PLACA_TIENE_DCACHE
  (void)p; (void)n;          /* Cortex-M4: no hay caché de datos */
#else
  if (!dcache_activa() || n == 0u) return;
  uint32_t a = (uint32_t)p & ~31u;
  uint32_t fin = ((uint32_t)p + n + 31u) & ~31u;
  SCB_CleanDCache_by_Addr((uint32_t *)a, (int32_t)(fin - a));
#endif
}

void cache_invalidar(const void *p, size_t n)
{
#if !PLACA_TIENE_DCACHE
  (void)p; (void)n;
#else
  if (!dcache_activa() || n == 0u) return;
  uint32_t a = (uint32_t)p & ~31u;
  uint32_t fin = ((uint32_t)p + n + 31u) & ~31u;
  SCB_InvalidateDCache_by_Addr((uint32_t *)a, (int32_t)(fin - a));
#endif
}

int leer_double(const char *s, double *v)
{
  double r = 0.0;
  int signo = 1, digitos = 0;
  if (*s == '+' || *s == '-') { if (*s == '-') signo = -1; s++; }
  while (*s >= '0' && *s <= '9') { r = r * 10.0 + (*s - '0'); s++; digitos++; }
  if (*s == '.') {
    double esc = 0.1;
    s++;
    while (*s >= '0' && *s <= '9') { r += (*s - '0') * esc; esc *= 0.1; s++; digitos++; }
  }
  if (digitos == 0) return 0;
  if (*s == 'e' || *s == 'E') {
    int es = 1, e = 0, de = 0;
    s++;
    if (*s == '+' || *s == '-') { if (*s == '-') es = -1; s++; }
    while (*s >= '0' && *s <= '9') { e = e * 10 + (*s - '0'); s++; de++; }
    if (de == 0) return 0;
    r *= pow(10.0, es * e);
  }
  if (*s != '\0') return 0;
  *v = signo * r;
  return isfinite(*v);
}

int fmt_double(char *buf, size_t n, double v, int dec)
{
  /* Sin %llu: newlib-nano (la libc de CubeIDE) no soporta enteros de 64 bits
   * en printf. Se separa en parte entera y decimal de 32 bits. */
  if (!isfinite(v)) return snprintf(buf, n, "nan");
  const char *signo = (v < 0) ? "-" : "";
  if (v < 0) v = -v;
  if (dec > 9) dec = 9;
  if (dec < 0) dec = 0;
  uint32_t esc = 1;
  for (int i = 0; i < dec; i++) esc *= 10u;
  double ent_d = floor(v);
  double frac_d = (v - ent_d) * (double)esc;
  uint32_t frac = (uint32_t)llround(frac_d);
  if (frac >= esc) { frac -= esc; ent_d += 1.0; }
  if (ent_d > 4294967295.0) ent_d = 4294967295.0;
  unsigned long ent = (unsigned long)ent_d;
  if (dec == 0) return snprintf(buf, n, "%s%lu", signo, ent);
  return snprintf(buf, n, "%s%lu.%0*lu", signo, ent, dec, (unsigned long)frac);
}
