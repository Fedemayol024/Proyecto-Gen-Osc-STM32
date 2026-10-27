/*
 * frecuencimetro.c - Ver frecuencimetro.h
 *
 * Recursos: PA0 (AF1 = TIM2_CH1 / TIM2_ETR), TIM2 (32 bits), TIM5 (compuerta)
 */
#include "frecuencimetro.h"
#include "hw_util.h"

typedef enum { M_CONTEO = 0, M_RECIPROCO } metodo_t;

static volatile int midiendo = 0;
static volatile int listo = 0;
static int continuo = 0;
static uint32_t compuerta_ms = 1000;
static metodo_t metodo = M_CONTEO;
static uint32_t prescaler_etr = 1;   /* 1 u 8 */
static uint32_t tclk;                /* reloj de TIM2/TIM5 */
static uint32_t ticks_compuerta;

static volatile uint32_t cuenta;
static volatile uint32_t n_flancos, t_primero, t_ultimo;
static fcnt_resultado_t ultimo;

void TIM2_IRQHandler(void)
{
  if (TIM2->SR & TIM_SR_CC1IF) {
    uint32_t t = TIM2->CCR1;          /* leer CCR1 borra el flag */
    if (n_flancos == 0u) t_primero = t;
    t_ultimo = t;
    n_flancos++;
  }
  TIM2->SR = ~(TIM_SR_CC1OF | TIM_SR_UIF);   /* bits rc_w0: escribir 0 los borra */
}

void TIM5_IRQHandler(void)
{
  if (TIM5->SR & TIM_SR_UIF) {
    TIM5->SR = ~TIM_SR_UIF;
    if (metodo == M_CONTEO) {
      cuenta = TIM2->CNT;
    }
    TIM2->CR1 &= ~TIM_CR1_CEN;
    TIM2->DIER = 0;
    midiendo = 0;
    listo = 1;
  }
}

void fcnt_iniciar(void)
{
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
  RCC->APB1ENR |= RCC_APB1ENR_TIM2EN | RCC_APB1ENR_TIM5EN;
  (void)RCC->APB1ENR;

  /* PA0 en función alternativa 1 (TIM2), con pull-down para que sin
   * señal no cuente ruido */
  GPIOA->MODER  = (GPIOA->MODER & ~(3u << 0)) | (2u << 0);
  GPIOA->AFR[0] = (GPIOA->AFR[0] & ~(0xFu << 0)) | (1u << 0);
  GPIOA->PUPDR  = (GPIOA->PUPDR & ~(3u << 0)) | (2u << 0);

  tclk = clk_tim_apb1();
  HAL_NVIC_SetPriority(TIM2_IRQn, PRIO_FRECUENC, 0);
  HAL_NVIC_SetPriority(TIM5_IRQn, PRIO_FRECUENC, 0);
  HAL_NVIC_EnableIRQ(TIM2_IRQn);
  HAL_NVIC_EnableIRQ(TIM5_IRQn);
}

static void arrancar(void)
{
  TIM2->CR1 = 0;
  TIM5->CR1 = 0;
  TIM2->DIER = 0;
  TIM5->DIER = 0;

  if (metodo == M_CONTEO) {
    TIM2->CCER = 0;
    TIM2->CCMR1 = 0;
    /* Modo reloj externo 2: cuenta flancos ascendentes de ETR */
    TIM2->SMCR = TIM_SMCR_ECE | ((prescaler_etr == 8u) ? (3u << TIM_SMCR_ETPS_Pos) : 0u);
    TIM2->PSC = 0;
    TIM2->ARR = 0xFFFFFFFFu;
  } else {
    TIM2->SMCR = 0;                         /* reloj interno */
    TIM2->PSC = 0;
    TIM2->ARR = 0xFFFFFFFFu;
    TIM2->CCMR1 = (1u << TIM_CCMR1_CC1S_Pos) | (2u << TIM_CCMR1_IC1F_Pos);  /* TI1, filtro corto */
    TIM2->CCER = TIM_CCER_CC1E;             /* flanco ascendente */
    n_flancos = 0;
  }
  TIM2->EGR = TIM_EGR_UG;
  TIM2->CNT = 0;
  TIM2->SR = 0;
  if (metodo == M_RECIPROCO) TIM2->DIER = TIM_DIER_CC1IE;

  /* TIM5: compuerta de un solo pulso */
  ticks_compuerta = (uint32_t)((uint64_t)tclk * compuerta_ms / 1000u);
  TIM5->PSC = 0;
  TIM5->ARR = ticks_compuerta - 1u;
  TIM5->CR1 = TIM_CR1_OPM | TIM_CR1_URS;
  TIM5->EGR = TIM_EGR_UG;
  TIM5->CNT = 0;
  TIM5->SR = 0;
  TIM5->DIER = TIM_DIER_UIE;

  midiendo = 1;
  listo = 0;
  __disable_irq();
  TIM2->CR1 |= TIM_CR1_CEN;
  TIM5->CR1 |= TIM_CR1_CEN;
  __enable_irq();
}

void fcnt_medir(uint32_t ms, int cont)
{
  if (ms < 10u) ms = 10u;
  if (ms > 10000u) ms = 10000u;
  compuerta_ms = ms;
  continuo = cont;
  arrancar();
}

void fcnt_detener(void)
{
  TIM5->CR1 = 0;
  TIM2->CR1 = 0;
  TIM2->DIER = 0;
  TIM5->DIER = 0;
  continuo = 0;
  midiendo = 0;
  listo = 0;
}

int fcnt_resultado(fcnt_resultado_t *r)
{
  if (!listo) return 0;
  listo = 0;

  double gate_s = (double)ticks_compuerta / (double)tclk;
  ultimo.compuerta_ms = compuerta_ms;
  if (metodo == M_CONTEO) {
    ultimo.metodo = 'C';
    ultimo.flancos = cuenta * prescaler_etr;
    ultimo.frecuencia = (double)cuenta * (double)prescaler_etr / gate_s;
  } else {
    ultimo.metodo = 'R';
    ultimo.flancos = n_flancos;
    ultimo.frecuencia = (n_flancos >= 2u && t_ultimo != t_primero)
                          ? (double)(n_flancos - 1u) * (double)tclk / (double)(t_ultimo - t_primero)
                          : 0.0;
  }
  *r = ultimo;

  /* Elegir el método y el prescaler para la próxima medición */
  double f = ultimo.frecuencia;
  if (metodo == M_CONTEO && f > 0.0 && f < 5000.0) metodo = M_RECIPROCO;
  else if (metodo == M_RECIPROCO && (f > 20000.0 || n_flancos > 200000u)) metodo = M_CONTEO;
  else if (metodo == M_RECIPROCO && n_flancos < 2u) metodo = M_CONTEO;
  prescaler_etr = (f > 20e6) ? 8u : 1u;

  if (continuo) arrancar();
  return 1;
}
