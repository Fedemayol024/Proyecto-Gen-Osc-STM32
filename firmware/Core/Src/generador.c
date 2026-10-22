/*
 * generador.c - Generador de 2 canales con DAC + DMA + TIM6 (ver generador.h)
 *
 * Recursos usados:
 *   DAC canal 1 -> PA4 (D24)      DAC canal 2 -> PA5 (D13)
 *   TIM6        -> disparo de los dos canales del DAC (~1 MS/s)
 *   DMA1 Stream5 Canal 7 -> registro DHR12RD del DAC (modo dual, 32 bits)
 */
#include "generador.h"
#include "hw_util.h"
#include <math.h>
#include <string.h>

#define FS_OBJETIVO   1000000.0      /* muestras por segundo por canal */
#define BLOQUE        256u           /* muestras por mitad de buffer */
#define MOD_TABLA_BITS 10u
#define MOD_TABLA_N   (1u << MOD_TABLA_BITS)
#define DOS_32        4294967296.0

typedef struct {
  uint16_t          tabla[2][GEN_TABLA_N];
  volatile uint8_t  activa;          /* tabla que usa la interrupción */
  volatile uint8_t  vista;           /* confirmación de la interrupción */
  volatile uint32_t inc;             /* incremento de fase por muestra */
  uint32_t          fase;
  volatile uint32_t fase_inicial;    /* fase relativa (sincronización) */
  volatile uint8_t  habilitado;
  volatile uint16_t reposo;          /* código cuando está deshabilitado */
  /* modulación */
  volatile uint8_t  mod;
  volatile float    am_prof;
  volatile float    centro;
  volatile float    fm_desvio_inc;
  volatile uint32_t mod_inc;
  uint32_t          mod_fase;
  /* barrido */
  volatile uint8_t  barrido;
  volatile double   bar_f1, bar_f2;
  volatile uint32_t bar_bloques;
  volatile uint32_t bar_k;           /* lo toca la ISR y el lazo principal */
} canal_t;

static canal_t canal[GEN_CANALES];
static uint32_t buf_dac[2u * BLOQUE] __attribute__((aligned(32)));
static float seno_mod[MOD_TABLA_N];
static double fs_real = FS_OBJETIVO;
static volatile uint8_t pedido_sincro = 0;
static volatile uint32_t subejecuciones = 0;

/* ------------------------------------------------------------------------ */
static void calcular_bloque(uint32_t *dst)
{
  if (pedido_sincro) {
    for (int c = 0; c < GEN_CANALES; c++) {
      canal[c].fase = canal[c].fase_inicial;
      canal[c].mod_fase = 0;
      canal[c].bar_k = 0;
    }
    pedido_sincro = 0;
  }

  for (int c = 0; c < GEN_CANALES; c++) {
    canal_t *ch = &canal[c];
    const unsigned desplaz = (c == 0) ? 0u : 16u;
    uint8_t act = ch->activa;
    ch->vista = act;
    const uint16_t *t = ch->tabla[act];

    if (!ch->habilitado) {
      uint32_t v = (uint32_t)ch->reposo << desplaz;
      for (uint32_t i = 0; i < BLOQUE; i++) {
        if (c == 0) dst[i] = v; else dst[i] |= v;
      }
      continue;
    }

    uint32_t inc = ch->inc;
    if (ch->barrido != GEN_BARR_NO && ch->bar_bloques > 0u) {
      double x = (double)ch->bar_k / (double)ch->bar_bloques;
      double f = (ch->barrido == GEN_BARR_LIN)
                   ? ch->bar_f1 + (ch->bar_f2 - ch->bar_f1) * x
                   : ch->bar_f1 * pow(ch->bar_f2 / ch->bar_f1, x);
      inc = (uint32_t)llround(f / fs_real * DOS_32);
      if (++ch->bar_k >= ch->bar_bloques) ch->bar_k = 0;
    }

    uint32_t fase = ch->fase;
    const uint8_t mod = ch->mod;

    if (mod == GEN_MOD_NINGUNA) {
      for (uint32_t i = 0; i < BLOQUE; i++) {
        uint32_t v = t[fase >> (32u - GEN_TABLA_BITS)];
        fase += inc;
        if (c == 0) dst[i] = v; else dst[i] |= v << 16;
      }
    } else if (mod == GEN_MOD_AM) {
      uint32_t mf = ch->mod_fase, minc = ch->mod_inc;
      float prof = ch->am_prof, centro = ch->centro;
      for (uint32_t i = 0; i < BLOQUE; i++) {
        float s = seno_mod[mf >> (32u - MOD_TABLA_BITS)];
        float v = centro + ((float)t[fase >> (32u - GEN_TABLA_BITS)] - centro) * (1.0f + prof * s);
        int32_t k = (int32_t)(v + 0.5f);
        if (k < 0) k = 0;
        if (k > 4095) k = 4095;
        fase += inc;
        mf += minc;
        if (c == 0) dst[i] = (uint32_t)k; else dst[i] |= (uint32_t)k << 16;
      }
      ch->mod_fase = mf;
    } else { /* FM */
      uint32_t mf = ch->mod_fase, minc = ch->mod_inc;
      float desv = ch->fm_desvio_inc;
      for (uint32_t i = 0; i < BLOQUE; i++) {
        float s = seno_mod[mf >> (32u - MOD_TABLA_BITS)];
        uint32_t v = t[fase >> (32u - GEN_TABLA_BITS)];
        fase += inc + (uint32_t)(int32_t)(desv * s);   /* suma sin signo: el desborde está definido */
        mf += minc;
        if (c == 0) dst[i] = v; else dst[i] |= v << 16;
      }
      ch->mod_fase = mf;
    }
    ch->fase = fase;
  }
  cache_limpiar(dst, BLOQUE * sizeof(uint32_t));
}

/* Interrupción del DMA del DAC: recalcula la mitad que acaba de salir */
void DMA1_Stream5_IRQHandler(void)
{
  uint32_t isr = DMA1->HISR;
  if (isr & DMA_HISR_HTIF5) {
    DMA1->HIFCR = DMA_HIFCR_CHTIF5;
    calcular_bloque(&buf_dac[0]);
  }
  if (isr & DMA_HISR_TCIF5) {
    DMA1->HIFCR = DMA_HIFCR_CTCIF5;
    calcular_bloque(&buf_dac[BLOQUE]);
  }
  if (isr & (DMA_HISR_TEIF5 | DMA_HISR_DMEIF5 | DMA_HISR_FEIF5)) {
    DMA1->HIFCR = DMA_HIFCR_CTEIF5 | DMA_HIFCR_CDMEIF5 | DMA_HIFCR_CFEIF5;
  }
}

/* ------------------------------------------------------------------------ */
static void arrancar_dma(void)
{
  DMA_Stream_TypeDef *s = DMA1_Stream5;
  s->CR &= ~DMA_SxCR_EN;
  for (uint32_t t = ESPERA_DMA_ITER; (s->CR & DMA_SxCR_EN) && t; t--) { }
  DMA1->HIFCR = DMA_HIFCR_CTCIF5 | DMA_HIFCR_CHTIF5 | DMA_HIFCR_CTEIF5 |
                DMA_HIFCR_CDMEIF5 | DMA_HIFCR_CFEIF5;

  calcular_bloque(&buf_dac[0]);
  calcular_bloque(&buf_dac[BLOQUE]);

  s->PAR  = (uint32_t)&DAC->DHR12RD;
  s->M0AR = (uint32_t)buf_dac;
  s->NDTR = 2u * BLOQUE;
  s->FCR  = 0;                                    /* modo directo */
  s->CR   = (7u << DMA_SxCR_CHSEL_Pos)            /* canal 7 = DAC1 */
          | DMA_SxCR_PL_1 | DMA_SxCR_PL_0         /* prioridad muy alta */
          | DMA_SxCR_MSIZE_1 | DMA_SxCR_PSIZE_1   /* 32 bits */
          | DMA_SxCR_MINC | DMA_SxCR_CIRC
          | DMA_SxCR_DIR_0                        /* memoria -> periférico */
          | DMA_SxCR_HTIE | DMA_SxCR_TCIE | DMA_SxCR_TEIE;
  s->CR  |= DMA_SxCR_EN;
}

void gen_iniciar(void)
{
  for (uint32_t i = 0; i < MOD_TABLA_N; i++) {
    seno_mod[i] = sinf(6.28318530718f * (float)i / (float)MOD_TABLA_N);
  }
  memset(canal, 0, sizeof(canal));
  for (int c = 0; c < GEN_CANALES; c++) {
    /* Arranque: DC en mitad de escala (≈ 0 V en la salida ±5 V de la placa) */
    canal[c].reposo = 2096;
    for (uint32_t i = 0; i < GEN_TABLA_N; i++) {
      canal[c].tabla[0][i] = 2096;
      canal[c].tabla[1][i] = 2096;
    }
    canal[c].centro = 2096.0f;
    canal[c].habilitado = 1;
  }

  /* Relojes */
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_DMA1EN;
  RCC->APB1ENR |= RCC_APB1ENR_DACEN | RCC_APB1ENR_TIM6EN;
  (void)RCC->APB1ENR;

  /* PA4 y PA5 en modo analógico */
  GPIOA->MODER |= (3u << (4u * 2u)) | (3u << (5u * 2u));
  GPIOA->PUPDR &= ~((3u << (4u * 2u)) | (3u << (5u * 2u)));

  /* TIM6: base de tiempo del DAC */
  uint32_t tclk = clk_tim_apb1();
  uint32_t arr = (uint32_t)lround((double)tclk / FS_OBJETIVO) - 1u;
  fs_real = (double)tclk / (double)(arr + 1u);
  TIM6->CR1 = 0;
  TIM6->PSC = 0;
  TIM6->ARR = arr;
  TIM6->CR2 = TIM_CR2_MMS_1;              /* TRGO = evento de actualización */
  TIM6->EGR = TIM_EGR_UG;

  /* DAC: los dos canales disparados por TIM6 (TSEL = 000), buffer de
   * salida activado, DMA solo en el canal 1 escribiendo DHR12RD (dual). */
  DAC->CR = 0;
  DAC->DHR12RD = (2096u << 16) | 2096u;
  DAC->CR = DAC_CR_TEN1 | DAC_CR_TEN2 | DAC_CR_DMAEN1;
  DAC->CR |= DAC_CR_EN1 | DAC_CR_EN2;

  arrancar_dma();
  HAL_NVIC_SetPriority(DMA1_Stream5_IRQn, PRIO_DAC_DMA, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream5_IRQn);

  TIM6->CR1 = TIM_CR1_CEN;
}

/* Si el DMA llegara tarde, el DAC deja de pedir datos: se rearma. Se llama
 * desde el lazo principal. */
void gen_vigilar(void)
{
  if (DAC->SR & DAC_SR_DMAUDR1) {
    subejecuciones++;
    TIM6->CR1 &= ~TIM_CR1_CEN;
    DAC->CR &= ~DAC_CR_DMAEN1;
    DAC->SR = DAC_SR_DMAUDR1;
    DAC->CR |= DAC_CR_DMAEN1;
    arrancar_dma();
    TIM6->CR1 |= TIM_CR1_CEN;
  }
}

uint32_t gen_subejecuciones(void) { return subejecuciones; }
double gen_fs(void) { return fs_real; }

uint16_t *gen_tabla_libre(int c)
{
  canal_t *ch = &canal[c];
  /* Esperar a que la interrupción ya use la tabla activa (máx. ~0,3 ms) */
  uint32_t t0 = HAL_GetTick();
  while (ch->vista != ch->activa && (HAL_GetTick() - t0) < 5u) { }
  return ch->tabla[ch->activa ^ 1u];
}

void gen_tabla_confirmar(int c)
{
  canal[c].activa ^= 1u;
}

double gen_configurar(int c, double frec, double fase_grados, int habilitado, uint16_t reposo)
{
  canal_t *ch = &canal[c];
  if (frec < 0) frec = 0;
  if (frec > 0.45 * fs_real) frec = 0.45 * fs_real;
  uint32_t inc = (uint32_t)llround(frec / fs_real * DOS_32);
  double f = fmod(fase_grados, 360.0);
  if (f < 0) f += 360.0;
  ch->fase_inicial = (uint32_t)llround(f / 360.0 * DOS_32);
  ch->reposo = (reposo > 4095u) ? 4095u : reposo;
  ch->inc = inc;
  ch->habilitado = habilitado ? 1u : 0u;
  return (double)inc * fs_real / DOS_32;
}

double gen_modulacion(int c, gen_mod_t tipo, double p, double frec_mod, double centro)
{
  canal_t *ch = &canal[c];
  if (frec_mod < 0) frec_mod = 0;
  if (frec_mod > 0.1 * fs_real) frec_mod = 0.1 * fs_real;
  ch->mod_inc = (uint32_t)llround(frec_mod / fs_real * DOS_32);
  if (centro < 0) centro = 0;
  if (centro > 4095) centro = 4095;
  ch->centro = (float)centro;
  if (tipo == GEN_MOD_AM) {
    if (p < 0) p = 0;
    if (p > 1) p = 1;
    ch->am_prof = (float)p;
  } else if (tipo == GEN_MOD_FM) {
    const double desvio_max = 0.45 * fs_real;   /* en Hz */
    if (p > desvio_max) p = desvio_max;
    if (p < -desvio_max) p = -desvio_max;
    ch->fm_desvio_inc = (float)(p / fs_real * DOS_32);
  }
  ch->mod = (uint8_t)tipo;
  return (double)ch->mod_inc * fs_real / DOS_32;
}

void gen_barrido(int c, gen_barrido_t modo, double f1, double f2, double tiempo_s)
{
  canal_t *ch = &canal[c];
  ch->barrido = GEN_BARR_NO;
  if (modo == GEN_BARR_NO) return;
  double fmax = 0.45 * fs_real;
  if (f1 < 0.01) f1 = 0.01;
  if (f2 < 0.01) f2 = 0.01;
  if (f1 > fmax) f1 = fmax;
  if (f2 > fmax) f2 = fmax;
  if (tiempo_s < 0.01) tiempo_s = 0.01;
  ch->bar_f1 = f1;
  ch->bar_f2 = f2;
  ch->bar_bloques = (uint32_t)llround(tiempo_s * fs_real / BLOQUE);
  if (ch->bar_bloques == 0u) ch->bar_bloques = 1u;
  ch->bar_k = 0;
  ch->barrido = (uint8_t)modo;
}

void gen_sincronizar(void)
{
  pedido_sincro = 1;
}
