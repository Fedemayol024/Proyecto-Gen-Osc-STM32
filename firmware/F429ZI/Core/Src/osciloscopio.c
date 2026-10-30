/*
 * osciloscopio.c - Captura de 2 canales con ADC1+ADC2 en modo dual
 *
 * Recursos usados:
 *   ADC1 canal 3  -> PA3 (A0)  = CH1
 *   ADC2 canal 10 -> PC0 (A1)  = CH2
 *   TIM8 TRGO     -> disparo de conversión (frecuencia de muestreo)
 *   DMA2 Stream0 Canal 0 -> ADC_CDR (dato común de los dos ADC, 32 bits)
 */
#include "osciloscopio.h"
#include "hw_util.h"
#include <math.h>

typedef enum { EST_LIBRE = 0, EST_CAPTURANDO, EST_COMPLETA, EST_LISTA } estado_t;

static uint32_t buf[OSC_MAX_MUESTRAS] __attribute__((aligned(32)));
static volatile estado_t estado = EST_LIBRE;
static volatile uint32_t errores_dma = 0;
static uint32_t reintentos = 0;        /* capturas que no terminaron y se rearmaron */
static uint32_t t_inicio;              /* HAL_GetTick() al arrancar la captura */
static uint32_t ms_esperados;          /* duración esperada de la captura */
static osc_param_t par;
static uint32_t total;
static double fs_real;
static uint32_t adcclk;
static uint32_t inicio_ventana;
static int disparado;

static const uint16_t ciclos_muestreo[8] = { 3, 15, 28, 56, 84, 112, 144, 480 };

void DMA2_Stream0_IRQHandler(void)
{
  uint32_t isr = DMA2->LISR;
  if (isr & DMA_LISR_TCIF0) {
    DMA2->LIFCR = DMA_LIFCR_CTCIF0;
    TIM8->CR1 &= ~TIM_CR1_CEN;
    estado = EST_COMPLETA;
  }
  if (isr & (DMA_LISR_TEIF0 | DMA_LISR_DMEIF0)) {
    /* Error de transferencia: el hardware ya apagó el stream. Se corta la
     * captura y se libera el estado para que la próxima no quede trabada. */
    TIM8->CR1 &= ~TIM_CR1_CEN;
    errores_dma++;
    estado = EST_LIBRE;
  }
  if (isr & (DMA_LISR_TEIF0 | DMA_LISR_DMEIF0 | DMA_LISR_FEIF0 | DMA_LISR_HTIF0)) {
    DMA2->LIFCR = DMA_LIFCR_CTEIF0 | DMA_LIFCR_CDMEIF0 | DMA_LIFCR_CFEIF0 | DMA_LIFCR_CHTIF0;
  }
}

void osc_iniciar(void)
{
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_GPIOCEN | RCC_AHB1ENR_DMA2EN;
  RCC->APB2ENR |= RCC_APB2ENR_ADC1EN | RCC_APB2ENR_ADC2EN | RCC_APB2ENR_TIM8EN;
  (void)RCC->APB2ENR;

  /* PA3 y PC0 analógicos */
  GPIOA->MODER |= 3u << (3u * 2u);
  GPIOA->PUPDR &= ~(3u << (3u * 2u));
  GPIOC->MODER |= 3u << (0u * 2u);
  GPIOC->PUPDR &= ~(3u << (0u * 2u));

  /* Reloj del ADC: el divisor más chico que deje ADCCLK <= 36 MHz */
  uint32_t pclk2 = HAL_RCC_GetPCLK2Freq();
  uint32_t div_bits = 3u, div = 8u;
  static const uint8_t divs[4] = { 2, 4, 6, 8 };
  for (uint32_t i = 0; i < 4u; i++) {
    if (pclk2 / divs[i] <= 36000000u) { div_bits = i; div = divs[i]; break; }
  }
  adcclk = pclk2 / div;

  ADC123_COMMON->CCR = (div_bits << ADC_CCR_ADCPRE_Pos);

  /* ADC1: 12 bits, 1 conversión (canal 3), disparo externo TIM8_TRGO */
  ADC1->CR1 = 0;
  ADC1->CR2 = 0;
  ADC1->SQR1 = 0;
  ADC1->SQR3 = 3u;
  /* ADC2: igual, canal 10, sin disparo propio (lo comanda ADC1) */
  ADC2->CR1 = 0;
  ADC2->CR2 = 0;
  ADC2->SQR1 = 0;
  ADC2->SQR3 = 10u;

  ADC1->CR2 |= ADC_CR2_ADON;
  ADC2->CR2 |= ADC_CR2_ADON;
  HAL_Delay(1);

  HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, PRIO_ADC_DMA, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

double osc_fs_max(void)
{
  /* 3 ciclos de muestreo + 12 de conversión + 2 de margen */
  return (double)adcclk / (3.0 + 12.0 + 2.0);
}

int osc_ocupado(void)
{
  return estado != EST_LIBRE;
}

/*
 * Corta la captura en curso y deja ADC + DMA como recién iniciados.
 *
 * Antes solo se apagaban el timer y el DMA. Si eso pasaba a mitad de una
 * captura (Single o Autoset con la adquisición corriendo), el ADC dual
 * quedaba con un dato sin leer, entraba en overrun (OVR) y dejaba de pedir
 * DMA: la captura siguiente no terminaba nunca y había que reiniciar la placa.
 * Ahora se cortan los pedidos de DMA del ADC, se vacían los datos, se borran
 * los flags y se reinician los dos ADC (ADON 0 -> 1).
 */
void osc_abortar(void)
{
  NVIC_DisableIRQ(DMA2_Stream0_IRQn);                 /* que no salte a mitad del corte */
  TIM8->CR1 &= ~TIM_CR1_CEN;                          /* no más disparos de conversión */
  ADC1->CR2 &= ~(ADC_CR2_EXTEN | ADC_CR2_EXTSEL);
  ADC123_COMMON->CCR &= ~(ADC_CCR_DMA | ADC_CCR_DDS); /* el ADC deja de pedir DMA */
  DMA2_Stream0->CR &= ~DMA_SxCR_EN;
  for (uint32_t t = ESPERA_DMA_ITER; (DMA2_Stream0->CR & DMA_SxCR_EN) && t; t--) { }
  DMA2->LIFCR = DMA_LIFCR_CTCIF0 | DMA_LIFCR_CHTIF0 | DMA_LIFCR_CTEIF0 |
                DMA_LIFCR_CDMEIF0 | DMA_LIFCR_CFEIF0;

  /* Vaciar y reiniciar los ADC: sin dato pendiente ni overrun */
  (void)ADC123_COMMON->CDR;
  (void)ADC1->DR;
  (void)ADC2->DR;
  ADC1->CR2 &= ~ADC_CR2_ADON;
  ADC2->CR2 &= ~ADC_CR2_ADON;
  ADC1->SR = 0;
  ADC2->SR = 0;
  ADC1->CR2 |= ADC_CR2_ADON;
  ADC2->CR2 |= ADC_CR2_ADON;
  /* tSTAB del ADC (~3 us): unas 1000 vueltas sobran a 216 MHz */
  for (volatile uint32_t t = 0; t < 1000u; t++) { }

  NVIC_ClearPendingIRQ(DMA2_Stream0_IRQn);
  NVIC_EnableIRQ(DMA2_Stream0_IRQn);
  estado = EST_LIBRE;
}

/*
 * Red de seguridad: si una captura tarda bastante más de lo que debería
 * (no llegó el fin del DMA), se rearma con los mismos parámetros en lugar de
 * esperar para siempre. Llamar desde el lazo principal.
 */
void osc_vigilar(void)
{
  if (estado != EST_CAPTURANDO) return;
  if (HAL_GetTick() - t_inicio > ms_esperados + 500u) {
    reintentos++;
    osc_param_t p = par;
    osc_capturar(&p);
  }
}

uint32_t osc_reintentos(void)
{
  return reintentos;
}

uint32_t osc_errores(void)
{
  return errores_dma;
}

double osc_capturar(const osc_param_t *p)
{
  osc_abortar();
  par = *p;

  if (par.n < 16u) par.n = 16u;
  if (par.n > OSC_MAX_VENTANA) par.n = OSC_MAX_VENTANA;
  if (par.pre > par.n) par.pre = par.n;
  if (par.hist < 1u) par.hist = 1u;
  if (par.hist > 4095u) par.hist = 4095u;
  if (par.nivel > 4095u) par.nivel = 4095u;
  if (par.fuente < 0 || par.fuente > 2) par.fuente = 0;

  double fsmax = osc_fs_max();
  double fs = par.fs;
  if (fs > fsmax) fs = fsmax;
  if (fs < 1.0) fs = 1.0;

  /* Muestras extra para buscar el disparo: hasta 2 ventanas más */
  uint32_t extra = 0;
  if (par.fuente != 0) {
    extra = 2u * par.n;
    if (par.n + extra > OSC_MAX_MUESTRAS) extra = OSC_MAX_MUESTRAS - par.n;
  }
  total = par.n + extra;

  /* Timer de muestreo TIM8 */
  uint32_t tclk = clk_tim_apb2();
  double cuentas = (double)tclk / fs;
  uint32_t psc = (uint32_t)ceil(cuentas / 65536.0);
  if (psc < 1u) psc = 1u;
  uint32_t arr = (uint32_t)lround(cuentas / (double)psc);
  if (arr < 2u) arr = 2u;
  if (arr > 65536u) arr = 65536u;
  fs_real = (double)tclk / ((double)psc * (double)arr);

  /* Tiempo de muestreo del ADC: el mayor que entre en el período */
  uint32_t smp = 0;
  for (int i = 7; i >= 0; i--) {
    double t_conv = (ciclos_muestreo[i] + 12.0) / (double)adcclk;
    if (t_conv * fs_real <= 0.92) { smp = (uint32_t)i; break; }
  }
  ADC1->SMPR2 = (ADC1->SMPR2 & ~(7u << (3u * 3u))) | (smp << (3u * 3u));     /* canal 3 */
  ADC2->SMPR1 = (ADC2->SMPR1 & ~(7u << (3u * 0u))) | (smp << (3u * 0u));     /* canal 10 */

  /* Limpiar estado de los ADC y rearmar el DMA del modo dual */
  ADC1->CR2 &= ~(ADC_CR2_EXTEN | ADC_CR2_EXTSEL);
  ADC1->SR = 0;
  ADC2->SR = 0;
  ADC123_COMMON->CCR &= ~(ADC_CCR_MULTI | ADC_CCR_DMA | ADC_CCR_DDS);
  ADC123_COMMON->CCR |= (6u << ADC_CCR_MULTI_Pos)       /* 00110: regular simultáneo */
                      | (2u << ADC_CCR_DMA_Pos);        /* modo DMA 2: 2 x 16 bits */

  DMA_Stream_TypeDef *s = DMA2_Stream0;
  s->PAR  = (uint32_t)&ADC123_COMMON->CDR;
  s->M0AR = (uint32_t)buf;
  s->NDTR = total;
  s->FCR  = 0;
  s->CR   = (0u << DMA_SxCR_CHSEL_Pos)                 /* canal 0 = ADC1 */
          | DMA_SxCR_PL_1                              /* prioridad alta */
          | DMA_SxCR_MSIZE_1 | DMA_SxCR_PSIZE_1        /* 32 bits */
          | DMA_SxCR_MINC
          | DMA_SxCR_TCIE | DMA_SxCR_TEIE;             /* periférico -> memoria */
  cache_invalidar(buf, total * sizeof(uint32_t));
  s->CR  |= DMA_SxCR_EN;

  /* TIM8: TRGO en cada actualización */
  TIM8->CR1 = 0;
  TIM8->CR2 = 0;
  TIM8->PSC = psc - 1u;
  TIM8->ARR = arr - 1u;
  TIM8->CNT = 0;
  TIM8->EGR = TIM_EGR_UG;            /* cargar PSC/ARR (todavía sin TRGO) */
  TIM8->SR = 0;
  TIM8->CR2 = TIM_CR2_MMS_1;         /* TRGO = actualización */

  /* Disparo externo del ADC1: TIM8_TRGO (código según la placa), flanco ascendente */
  ADC1->CR2 |= (PLACA_ADC_EXTSEL_TIM8_TRGO << ADC_CR2_EXTSEL_Pos) | ADC_CR2_EXTEN_0;

  double ms = 1000.0 * (double)total / fs_real;
  ms_esperados = (ms > 600000.0) ? 600000u : (uint32_t)ms;
  t_inicio = HAL_GetTick();
  estado = EST_CAPTURANDO;
  TIM8->CR1 = TIM_CR1_CEN;
  return fs_real;
}

/* Busca el disparo en el buffer completo */
static void procesar(void)
{
  cache_invalidar(buf, total * sizeof(uint32_t));
  inicio_ventana = 0;
  if (par.fuente == 0) { disparado = 2; return; }

  const unsigned desplaz = (par.fuente == 1) ? 0u : 16u;
  const int32_t nivel = par.nivel;
  const int32_t h = par.hist;
  /* Umbrales de armado acotados al rango del ADC: con nivel < histéresis (o
   * nivel + histéresis > 4095) el disparo igual puede armarse. */
  const int32_t umbral_sube = (nivel > h) ? nivel - h : 0;
  const int32_t umbral_baja = (nivel + h < 4095) ? nivel + h : 4095;
  const uint32_t desde = (par.pre > 0u) ? par.pre : 1u;
  const uint32_t hasta = total - (par.n - par.pre);   /* último índice válido */
  int armado = 0;
  disparado = 0;

  for (uint32_t i = 0; i <= hasta && i < total; i++) {
    int32_t v = (int32_t)((buf[i] >> desplaz) & 0xFFFu);
    if (par.flanco == OSC_FLANCO_SUBE) {
      if (v <= umbral_sube) armado = 1;
      else if (armado && v >= nivel) {
        if (i >= desde) { inicio_ventana = i - par.pre; disparado = 1; break; }
        else armado = 0;   /* se cruzó el nivel muy pronto: esperar el siguiente ciclo */
      }
    } else {
      if (v >= umbral_baja) armado = 1;
      else if (armado && v <= nivel) {
        if (i >= desde) { inicio_ventana = i - par.pre; disparado = 1; break; }
        else armado = 0;
      }
    }
  }
  if (!disparado) inicio_ventana = 0;   /* automático: ventana sin disparo */
}

int osc_listo(void)
{
  if (estado == EST_COMPLETA) {
    procesar();
    estado = EST_LISTA;
  }
  return estado == EST_LISTA;
}

const uint32_t *osc_ventana(uint32_t *n, uint32_t *pre, double *fs, int *disp)
{
  *n = par.n;
  *pre = par.pre;
  *fs = fs_real;
  *disp = disparado;
  return &buf[inicio_ventana];
}

void osc_liberar(void)
{
  if (estado == EST_LISTA) estado = EST_LIBRE;
}
