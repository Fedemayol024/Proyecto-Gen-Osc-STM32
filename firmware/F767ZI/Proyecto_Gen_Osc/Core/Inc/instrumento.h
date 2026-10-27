/*
 * instrumento.h - Punto de entrada del instrumento (generador + osciloscopio
 * + frecuencímetro + PWM) para NUCLEO-F767ZI y NUCLEO-F429ZI.
 *
 * Integración con el proyecto generado por STM32CubeIDE:
 *   main.c          -> instrumento_iniciar() antes del while(1)
 *                      instrumento_lazo()    dentro del while(1)
 *   usbd_cdc_if.c   -> instrumento_usb_rx(Buf, *Len) en CDC_Receive_FS
 */
#ifndef INSTRUMENTO_H
#define INSTRUMENTO_H

#include <stdint.h>

#define INSTR_VERSION "1.0"

void instrumento_iniciar(void);
void instrumento_lazo(void);
void instrumento_usb_rx(uint8_t *buf, uint32_t len);   /* se llama desde la interrupción USB */

#endif
