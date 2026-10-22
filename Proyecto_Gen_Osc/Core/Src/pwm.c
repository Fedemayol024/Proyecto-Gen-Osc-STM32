/*
 * pwm.c - Ver pwm.h
 */
#include "pwm.h"
#include "hw_util.h"
#include <math.h>

static void pin_af1(uint32_t pin)
{
  GPIOE->MODER   = (GPIOE->MODER & ~(3u << (pin * 2u))) | (2u << (pin * 2u));
  GPIOE->OSPEEDR |= 3u << (pin * 2u);                       /* muy alta velocidad */
  GPIOE->PUPDR   &= ~(3u << (pin * 2u));
  if (pin < 8u) GPIOE->AFR[0] = (GPIOE->AFR[0] & ~(0xFu << (pin * 4u))) | (1u << (pin * 4u));
  else          GPIOE->AFR[1] = (GPIOE->AFR[1] & ~(0xFu << ((pin - 8u) * 4u))) | (1u << ((pin - 8u) * 4u));
}

void pwm_iniciar(void)
{
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
  RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
  (void)RCC->APB2ENR;
  pin_af1(9);
  pin_af1(8);

  TIM1->CR1 = 0;
  TIM1->BDTR = TIM_BDTR_OSSI;      /* con MOE = 0 las salidas quedan en 0 */
  TIM1->CCMR1 = (6u << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;   /* PWM modo 1 */
  TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE;
  TIM1->CR2 = 0;                   /* OIS1 = OIS1N = 0 (reposo en bajo) */
}

/* Codifica el tiempo muerto en el campo DTG (tDTS = 1/fclk del timer) */
static uint32_t codificar_dtg(double tm_s, double t_dts, double *real)
{
  double n = tm_s / t_dts;
  uint32_t dtg;
  if (n <= 127.0) {
    uint32_t k = (uint32_t)lround(n);
    dtg = k;
    *real = k * t_dts;
  } else if (n <= (64.0 + 63.0) * 2.0) {
    uint32_t k = (uint32_t)lround(n / 2.0 - 64.0);
    if (k > 63u) k = 63u;
    dtg = 0x80u | k;
    *real = (64.0 + k) * 2.0 * t_dts;
  } else if (n <= (32.0 + 31.0) * 8.0) {
    uint32_t k = (uint32_t)lround(n / 8.0 - 32.0);
    if (k > 31u) k = 31u;
    dtg = 0xC0u | k;
    *real = (32.0 + k) * 8.0 * t_dts;
  } else {
    long kk = lround(n / 16.0 - 32.0);
    uint32_t k = (kk < 0) ? 0u : (kk > 31 ? 31u : (uint32_t)kk);
    dtg = 0xE0u | k;
    *real = (32.0 + k) * 16.0 * t_dts;
  }
  return dtg;
}

void pwm_configurar(double frec, double ciclo, double tm_ns, int hab,
                    double *frec_real, double *ciclo_real, double *tm_real)
{
  uint32_t tclk = clk_tim_apb2();
  if (frec < 1.0) frec = 1.0;
  if (frec > tclk / 4.0) frec = tclk / 4.0;
  if (ciclo < 0.0) ciclo = 0.0;
  if (ciclo > 100.0) ciclo = 100.0;
  if (tm_ns < 0.0) tm_ns = 0.0;
  /* Mayor tiempo muerto que codifica el DTG: (32 + 31) * 16 * tDTS */
  const double tm_max_ns = (32.0 + 31.0) * 16.0 / (double)tclk * 1e9;
  if (tm_ns > tm_max_ns) tm_ns = tm_max_ns;

  double cuentas = (double)tclk / frec;
  uint32_t psc = (uint32_t)ceil(cuentas / 65536.0);
  if (psc < 1u) psc = 1u;
  uint32_t periodo = (uint32_t)lround(cuentas / (double)psc);
  if (periodo < 4u) periodo = 4u;
  if (periodo > 65536u) periodo = 65536u;
  uint32_t ccr = (uint32_t)lround(periodo * ciclo / 100.0);

  double tm_r = 0.0;
  uint32_t dtg = codificar_dtg(tm_ns * 1e-9, 1.0 / (double)tclk, &tm_r);

  TIM1->BDTR &= ~TIM_BDTR_MOE;
  TIM1->CR1 = TIM_CR1_ARPE;
  TIM1->PSC = psc - 1u;
  TIM1->ARR = periodo - 1u;
  TIM1->CCR1 = ccr;
  TIM1->BDTR = TIM_BDTR_OSSI | TIM_BDTR_OSSR | (dtg << TIM_BDTR_DTG_Pos);
  TIM1->EGR = TIM_EGR_UG;
  if (hab) {
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_CEN;
  } else {
    TIM1->CR1 &= ~TIM_CR1_CEN;
  }

  *frec_real = (double)tclk / ((double)psc * (double)periodo);
  *ciclo_real = 100.0 * (double)ccr / (double)periodo;
  *tm_real = tm_r * 1e9;
}
