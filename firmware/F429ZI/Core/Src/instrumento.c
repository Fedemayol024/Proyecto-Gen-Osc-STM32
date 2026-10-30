/*
 * instrumento.c - Comunicación USB y protocolo de comandos del instrumento
 *
 * Todo viaja por el USB nativo (conector USB "USER" CN13) como puerto COM
 * virtual. Los comandos son líneas de texto terminadas en '\n'. Las únicas
 * partes binarias son:
 *   - la tabla que manda la PC después de "GTBL"
 *   - los datos del osciloscopio que manda la placa después de "DATA"
 *
 * Comandos (ver también LEEME.md):
 *   ID?                         -> INSTR-F767 v0.8.18  (o INSTR-F429 v0.8.18)
 *   INFO?                       -> INFO gen_fs=.. osc_fsmax=.. tabla=4096 ventana=8192 ..
 *                                  reinicio=watchdog|energia|boton|software|otro
 *   GTBL c n suma  + 2n bytes   -> OK GTBL c        (tabla de c = 1|2, uint16 LE)
 *   GSET c frec fase hab reposo -> OK GSET c frec_real
 *   GMOD c NO|AM|FM p fmod centro -> OK GMOD c fmod_real
 *   GSWP c NO|LIN|LOG f1 f2 t   -> OK GSWP c
 *   GSYNC                       -> OK GSYNC
 *   CAP n pre fs fuente nivel flanco hist
 *                               -> DATA n pre fs disparado + 4n bytes
 *   CAPX                        -> OK CAPX          (cancela la captura)
 *   FCNT ms continuo            -> FREQ f metodo flancos ms  (ms = 0 detiene)
 *   PWM frec ciclo tm_ns hab    -> OK PWM frec_real ciclo_real tm_real
 *   STAT?                       -> STAT subejec=.. osc=.. osc_err=.. tx_perd=.. osc_rein=..
 *   DDS frec forma hab          -> OK DDS frec_real    (módulo AD9833; forma 0 seno,
 *                                                       1 triangular, 2 cuadrada)
 *   DDSA paso                   -> OK DDSA paso        (amplitud, 0..255)
 */
#include "instrumento.h"
#include "hw_util.h"
#include "generador.h"
#include "osciloscopio.h"
#include "frecuencimetro.h"
#include "pwm.h"
#include "ad9833.h"

#include "usbd_def.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

/* ------------------------------------------------------------------------
 * Recepción: buffer circular que llena la interrupción USB
 * ---------------------------------------------------------------------- */
#define RX_TAM 16384u
static uint8_t rx_buf[RX_TAM];
static volatile uint32_t rx_esc = 0, rx_lec = 0;
static uint8_t *volatile rx_pendiente = NULL;   /* paquete USB sin rearmar */

static uint32_t rx_libre(void)
{
  return RX_TAM - 1u - ((rx_esc - rx_lec) & (RX_TAM - 1u));
}

static void rx_rearmar(uint8_t *buf)
{
  USBD_CDC_SetRxBuffer(&hUsbDeviceFS, buf);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);
}

void instrumento_usb_rx(uint8_t *buf, uint32_t len)
{
  for (uint32_t i = 0; i < len; i++) {
    rx_buf[rx_esc & (RX_TAM - 1u)] = buf[i];
    rx_esc++;
  }
  /* Control de flujo: si no entra otro paquete, no se rearma la recepción
   * (el host espera) hasta que el lazo principal libere lugar. */
  if (rx_libre() >= 2u * 64u) rx_rearmar(buf);
  else rx_pendiente = buf;
}

/* ------------------------------------------------------------------------
 * Transmisión
 * ---------------------------------------------------------------------- */
#define TX_TEXTO 2048u
static char tx_pend[TX_TEXTO];
static uint32_t tx_pend_len = 0;
static uint32_t tx_perdidas = 0;       /* respuestas descartadas, sin avisar todavía */
static uint32_t tx_perdidas_total = 0;
static char tx_envio[TX_TEXTO];
static char cab_datos[96];

typedef enum { TRAMA_NO = 0, TRAMA_CABECERA, TRAMA_DATOS, TRAMA_ESPERA_FIN } trama_t;
static trama_t trama = TRAMA_NO;
static const uint8_t *trama_ptr;
static uint32_t trama_len;

static int usb_listo(void)
{
  return hUsbDeviceFS.dev_state == USBD_STATE_CONFIGURED && hUsbDeviceFS.pClassData != NULL;
}

static int usb_tx_libre(void)
{
  if (!usb_listo()) return 0;
  USBD_CDC_HandleTypeDef *h = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  return h->TxState == 0u;
}

static void responder(const char *fmt, ...)
{
  char linea[256];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(linea, sizeof(linea) - 1u, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if ((uint32_t)n > sizeof(linea) - 2u) n = (int)sizeof(linea) - 2;
  linea[n++] = '\n';
  if (tx_pend_len + (uint32_t)n <= TX_TEXTO) {
    memcpy(&tx_pend[tx_pend_len], linea, (size_t)n);
    tx_pend_len += (uint32_t)n;
  } else {
    tx_perdidas++;
    tx_perdidas_total++;
  }
}

static void tx_atender(void)
{
  if (!usb_listo()) {
    /* Sin USB: descartar lo pendiente para no trabar el osciloscopio */
    tx_pend_len = 0;
    if (trama != TRAMA_NO) { trama = TRAMA_NO; osc_liberar(); }
    return;
  }
  if (!usb_tx_libre()) return;

  switch (trama) {
    case TRAMA_CABECERA:
      CDC_Transmit_FS((uint8_t *)cab_datos, (uint16_t)strlen(cab_datos));
      trama = TRAMA_DATOS;
      return;
    case TRAMA_DATOS:
      CDC_Transmit_FS((uint8_t *)trama_ptr, (uint16_t)trama_len);
      trama = TRAMA_ESPERA_FIN;
      return;
    case TRAMA_ESPERA_FIN:
      trama = TRAMA_NO;          /* el envío anterior terminó: buffer libre */
      osc_liberar();
      break;
    default:
      break;
  }
  if (tx_pend_len > 0u) {
    memcpy(tx_envio, tx_pend, tx_pend_len);
    uint16_t n = (uint16_t)tx_pend_len;
    tx_pend_len = 0;
    CDC_Transmit_FS((uint8_t *)tx_envio, n);
    if (tx_perdidas > 0u) {            /* avisar al host que se perdieron respuestas */
      uint32_t perdidas = tx_perdidas;
      tx_perdidas = 0;
      responder("ERR tx_lleno perdidas=%lu", (unsigned long)perdidas);
    }
  }
}

/* ------------------------------------------------------------------------
 * Comandos
 * ---------------------------------------------------------------------- */
#define MAX_TOK 10
static char linea[256];
static uint32_t linea_len = 0;

/* Recepción binaria de tablas */
static int bin_activo = 0;
static int bin_canal;
static uint16_t *bin_dest;
static uint32_t bin_restantes, bin_idx, bin_suma, bin_suma_esperada;
static uint8_t bin_lsb;
static uint32_t bin_t_ultimo;          /* HAL_GetTick() del último byte recibido */
#define BIN_TIMEOUT_MS 500u            /* sin bytes por este tiempo: se aborta la tabla */

/* Captura pedida mientras se enviaba la anterior */
static int cap_pendiente = 0;
static osc_param_t cap_param;

static int num(const char *s, double *v) { return s && leer_double(s, v); }

/* Conversión double -> entero sin signo con saturación (un negativo o un valor
 * enorme no pueden dar la vuelta; el resultado de ese cast sería indefinido). */
static uint16_t saturar_u16(double v)
{
  if (!(v > 0.0)) return 0u;               /* también cubre NaN */
  if (v > 65535.0) return 65535u;
  return (uint16_t)v;
}

static uint32_t saturar_u32(double v)
{
  if (!(v > 0.0)) return 0u;
  if (v > 4294967040.0) return 4294967040u;
  return (uint32_t)v;
}

static int canal_valido(const char *s, int *c)
{
  double v;
  if (!num(s, &v) || (v != 1.0 && v != 2.0)) return 0;
  *c = (int)v - 1;
  return 1;
}

static void cmd_info(void)
{
  char a[24], b[24];
  fmt_double(a, sizeof a, gen_fs(), 3);
  fmt_double(b, sizeof b, osc_fs_max(), 3);
  responder("INFO gen_fs=%s osc_fsmax=%s tabla=%u ventana=%u cpu=%lu wdg_ms=%lu reinicio=%s dds_mclk=%lu",
            a, b, (unsigned)GEN_TABLA_N, (unsigned)OSC_MAX_VENTANA, (unsigned long)SystemCoreClock,
            (unsigned long)WDG_MS, causa_reinicio(), (unsigned long)DDS_MCLK_HZ);
}

static void procesar_linea(char *l)
{
  char *tok[MAX_TOK];
  int nt = 0;
  for (char *p = strtok(l, " \t,"); p && nt < MAX_TOK; p = strtok(NULL, " \t,")) tok[nt++] = p;
  if (nt == 0) return;
  const char *c0 = tok[0];
  double v[8];
  char a[24], b[24], d[24];

  if (!strcmp(c0, "ID?")) { responder("INSTR-" PLACA_ID " v" INSTR_VERSION); return; }
  if (!strcmp(c0, "INFO?")) { cmd_info(); return; }

  if (!strcmp(c0, "GTBL")) {
    int c;
    if (nt < 4 || !canal_valido(tok[1], &c) || !num(tok[2], &v[0]) || !num(tok[3], &v[1]) ||
        v[0] != (double)GEN_TABLA_N) {
      responder("ERR GTBL: GTBL canal 4096 suma");
      return;
    }
    bin_activo = 1;
    bin_canal = c;
    bin_dest = gen_tabla_libre(c);
    bin_restantes = 2u * GEN_TABLA_N;
    bin_idx = 0;
    bin_suma = 0;
    bin_suma_esperada = saturar_u32(v[1]);
    bin_t_ultimo = HAL_GetTick();
    return;
  }

  if (!strcmp(c0, "GSET")) {
    int c;
    if (nt < 6 || !canal_valido(tok[1], &c) || !num(tok[2], &v[0]) || !num(tok[3], &v[1]) ||
        !num(tok[4], &v[2]) || !num(tok[5], &v[3])) {
      responder("ERR GSET: GSET canal frec fase hab reposo");
      return;
    }
    double fr = gen_configurar(c, v[0], v[1], v[2] != 0.0, saturar_u16(v[3]));
    fmt_double(a, sizeof a, fr, 6);
    responder("OK GSET %d %s", c + 1, a);
    return;
  }

  if (!strcmp(c0, "GMOD")) {
    int c;
    gen_mod_t t;
    if (nt < 6 || !canal_valido(tok[1], &c) || !num(tok[3], &v[0]) || !num(tok[4], &v[1]) ||
        !num(tok[5], &v[2])) {
      responder("ERR GMOD: GMOD canal NO|AM|FM param fmod centro");
      return;
    }
    if (!strcmp(tok[2], "AM")) t = GEN_MOD_AM;
    else if (!strcmp(tok[2], "FM")) t = GEN_MOD_FM;
    else t = GEN_MOD_NINGUNA;
    double fm = gen_modulacion(c, t, v[0], v[1], v[2]);
    fmt_double(a, sizeof a, fm, 6);
    responder("OK GMOD %d %s", c + 1, a);
    return;
  }

  if (!strcmp(c0, "GSWP")) {
    int c;
    gen_barrido_t m;
    if (nt < 3 || !canal_valido(tok[1], &c)) { responder("ERR GSWP: GSWP canal NO|LIN|LOG f1 f2 t"); return; }
    if (!strcmp(tok[2], "LIN")) m = GEN_BARR_LIN;
    else if (!strcmp(tok[2], "LOG")) m = GEN_BARR_LOG;
    else m = GEN_BARR_NO;
    if (m != GEN_BARR_NO && (nt < 6 || !num(tok[3], &v[0]) || !num(tok[4], &v[1]) || !num(tok[5], &v[2]))) {
      responder("ERR GSWP: GSWP canal NO|LIN|LOG f1 f2 t");
      return;
    }
    gen_barrido(c, m, v[0], v[1], v[2]);
    responder("OK GSWP %d", c + 1);
    return;
  }

  if (!strcmp(c0, "GSYNC")) { gen_sincronizar(); responder("OK GSYNC"); return; }

  if (!strcmp(c0, "CAP")) {
    if (nt < 8) { responder("ERR CAP: CAP n pre fs fuente nivel flanco hist"); return; }
    for (int i = 0; i < 7; i++) {
      if (!num(tok[i + 1], &v[i])) { responder("ERR CAP: numero invalido"); return; }
    }
    osc_param_t p;
    p.n = saturar_u32(v[0]);
    p.pre = saturar_u32(v[1]);
    p.fs = v[2];
    p.fuente = (v[3] < 0.5) ? 0 : ((v[3] < 1.5) ? 1 : 2);
    p.nivel = saturar_u16(v[4]);
    p.flanco = (v[5] != 0.0) ? OSC_FLANCO_BAJA : OSC_FLANCO_SUBE;
    p.hist = saturar_u16(v[6]);
    if (trama != TRAMA_NO) {        /* se está enviando la anterior */
      cap_param = p;
      cap_pendiente = 1;
    } else {
      osc_capturar(&p);
    }
    return;
  }

  if (!strcmp(c0, "CAPX")) {
    cap_pendiente = 0;
    if (trama == TRAMA_NO) osc_abortar();
    responder("OK CAPX");
    return;
  }

  if (!strcmp(c0, "FCNT")) {
    if (nt < 3 || !num(tok[1], &v[0]) || !num(tok[2], &v[1])) { responder("ERR FCNT: FCNT ms continuo"); return; }
    if (v[0] <= 0.0) { fcnt_detener(); responder("OK FCNT 0"); }
    else { fcnt_medir((uint32_t)v[0], v[1] != 0.0); responder("OK FCNT %lu", (unsigned long)v[0]); }
    return;
  }

  if (!strcmp(c0, "PWM")) {
    if (nt < 5 || !num(tok[1], &v[0]) || !num(tok[2], &v[1]) || !num(tok[3], &v[2]) || !num(tok[4], &v[3])) {
      responder("ERR PWM: PWM frec ciclo tm_ns hab");
      return;
    }
    double fr, cr, tr;
    pwm_configurar(v[0], v[1], v[2], v[3] != 0.0, &fr, &cr, &tr);
    fmt_double(a, sizeof a, fr, 4);
    fmt_double(b, sizeof b, cr, 3);
    fmt_double(d, sizeof d, tr, 2);
    responder("OK PWM %s %s %s", a, b, d);
    return;
  }

  if (!strcmp(c0, "DDS")) {
    if (nt < 4 || !num(tok[1], &v[0]) || !num(tok[2], &v[1]) || !num(tok[3], &v[2]) ||
        v[1] < 0.0 || v[1] > 2.0) {
      responder("ERR DDS: DDS frec forma(0 seno,1 triangular,2 cuadrada) hab");
      return;
    }
    double fr = dds_configurar(v[0], (dds_forma_t)(int)v[1], v[2] != 0.0);
    fmt_double(a, sizeof a, fr, 4);
    responder("OK DDS %s", a);
    return;
  }

  if (!strcmp(c0, "DDSA")) {
    if (nt < 2 || !num(tok[1], &v[0]) || v[0] < 0.0 || v[0] > 255.0) {
      responder("ERR DDSA: DDSA paso(0..255)");
      return;
    }
    dds_amplitud((uint8_t)lround(v[0]));
    responder("OK DDSA %u", (unsigned)lround(v[0]));
    return;
  }

  if (!strcmp(c0, "STAT?")) {
    responder("STAT subejec=%lu osc=%d osc_err=%lu tx_perd=%lu osc_rein=%lu", (unsigned long)gen_subejecuciones(),
              osc_ocupado(), (unsigned long)osc_errores(), (unsigned long)tx_perdidas_total,
              (unsigned long)osc_reintentos());
    return;
  }

  responder("ERR comando desconocido: %s", c0);
}

static void procesar_rx(void)
{
  /* Tabla binaria a medio recibir y sin bytes nuevos: se perdió algo en el
   * camino. Se aborta para volver a aceptar comandos de texto. */
  if (bin_activo && rx_lec == rx_esc && (HAL_GetTick() - bin_t_ultimo) > BIN_TIMEOUT_MS) {
    bin_activo = 0;
    responder("ERR GTBL timeout (%lu de %lu bytes)",
              (unsigned long)(2u * GEN_TABLA_N - bin_restantes), (unsigned long)(2u * GEN_TABLA_N));
  }

  uint32_t limite = 4096;   /* no acaparar el lazo */
  while (rx_lec != rx_esc && limite--) {
    uint8_t ch = rx_buf[rx_lec & (RX_TAM - 1u)];
    rx_lec++;

    if (bin_activo) {
      bin_t_ultimo = HAL_GetTick();
      if ((bin_restantes & 1u) == 0u) {
        bin_lsb = ch;
      } else {
        uint16_t val = (uint16_t)(bin_lsb | ((uint16_t)ch << 8));
        if (val > 4095u) val = 4095u;
        bin_dest[bin_idx++] = val;
        bin_suma += val;
      }
      if (--bin_restantes == 0u) {
        bin_activo = 0;
        if (bin_suma == bin_suma_esperada) {
          cache_limpiar(bin_dest, GEN_TABLA_N * sizeof(uint16_t));
          gen_tabla_confirmar(bin_canal);
          responder("OK GTBL %d", bin_canal + 1);
        } else {
          responder("ERR GTBL suma %lu != %lu", (unsigned long)bin_suma, (unsigned long)bin_suma_esperada);
        }
      }
      continue;
    }

    if (ch == '\r') continue;
    if (ch == '\n') {
      linea[linea_len] = '\0';
      if (linea_len > 0u) procesar_linea(linea);
      linea_len = 0;
      continue;
    }
    if (linea_len < sizeof(linea) - 1u) linea[linea_len++] = (char)ch;
  }

  if (rx_pendiente && rx_libre() >= 2u * 64u) {
    uint8_t *b = rx_pendiente;
    rx_pendiente = NULL;
    rx_rearmar(b);
  }
}

/* ------------------------------------------------------------------------ */
void instrumento_iniciar(void)
{
  /* LD2 (PB7, azul): parpadea mientras el programa está corriendo.
   * LD1 (verde) y LD3 (rojo) no se usan: quedan apagados. */
  RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
  (void)RCC->AHB1ENR;
  GPIOB->MODER = (GPIOB->MODER & ~(3u << 14)) | (1u << 14);
  GPIOB->ODR &= ~((1u << 0) | (1u << 7) | (1u << 14));

  gen_iniciar();
  osc_iniciar();
  fcnt_iniciar();
  pwm_iniciar();
  dds_iniciar();

  /* Último: si algo de lo anterior se colgara, no hay watchdog todavía y se ve
   * en el depurador; desde acá, un cuelgue reinicia la placa sola. */
  wdg_iniciar(WDG_MS);
}

void instrumento_lazo(void)
{
  static uint32_t t_led = 0;
  wdg_patear();                          /* el lazo sigue vivo */
  if (HAL_GetTick() - t_led >= 250u) {   /* LD2 azul: latido */
    t_led = HAL_GetTick();
    GPIOB->ODR ^= (1u << 7);
  }
  procesar_rx();
  gen_vigilar();

  /* Osciloscopio: preparar el envío de la ventana capturada */
  if (trama == TRAMA_NO && osc_listo()) {
    uint32_t n, pre;
    double fs;
    int disp;
    trama_ptr = (const uint8_t *)osc_ventana(&n, &pre, &fs, &disp);
    trama_len = n * 4u;
    char f[24];
    fmt_double(f, sizeof f, fs, 4);
    snprintf(cab_datos, sizeof cab_datos, "DATA %lu %lu %s %d\n",
             (unsigned long)n, (unsigned long)pre, f, disp);
    trama = TRAMA_CABECERA;
  }
  if (trama == TRAMA_NO && cap_pendiente) {
    cap_pendiente = 0;
    osc_capturar(&cap_param);
  }
  osc_vigilar();                         /* captura trabada: rearmarla */

  fcnt_resultado_t r;
  if (fcnt_resultado(&r)) {
    char f[32];
    fmt_double(f, sizeof f, r.frecuencia, 6);
    responder("FREQ %s %c %lu %lu", f, r.metodo, (unsigned long)r.flancos, (unsigned long)r.compuerta_ms);
  }

  tx_atender();
}
