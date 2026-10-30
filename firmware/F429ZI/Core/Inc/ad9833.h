/*
 * ad9833.h - Generador DDS externo: módulo AD9833 + MCP41010 + AD8051
 *
 * El módulo trae:
 *   AD9833   DDS de 28 bits con reloj de 25 MHz: seno, triangular o cuadrada
 *            de 0,1 Hz a 12,5 MHz (limpio hasta unos pocos MHz).
 *   MCP41010 potenciómetro digital de 10 kΩ (256 pasos): fija la ganancia del
 *            AD8051, o sea la amplitud de la salida amplificada.
 *
 * Conexión (conector CN8, iguales en F767ZI y F429ZI):
 *   PC10 (D45) -> CLK      PC12 (D47) -> DAT
 *   PD2  (D48) -> FSY  (selección del AD9833)
 *   PG2  (D49) -> CS   (selección del MCP41010)
 *   3V3 -> VCC, GND -> GND  (alimentar con 3,3 V)
 *
 * El SPI se hace por software (bit-bang): son pocos bytes por cambio, y así el
 * mismo código anda en el F7 y en el F4 (sus SPI por hardware son distintos).
 * Reloj en reposo alto: el AD9833 lee en el flanco de bajada y el MCP41010 en
 * el de subida; con el dato quieto durante el pulso, los dos lo leen bien.
 */
#ifndef AD9833_H
#define AD9833_H

#include <stdint.h>

#define DDS_MCLK_HZ   25000000.0   /* oscilador del módulo */
#define DDS_F_MAX     12500000.0   /* Nyquist del DDS */

typedef enum { DDS_SENO = 0, DDS_TRIANGULAR = 1, DDS_CUADRADA = 2 } dds_forma_t;

void   dds_iniciar(void);
/* Configura frecuencia y forma. Si habilitado = 0, la salida queda apagada
 * (DAC del AD9833 dormido). Devuelve la frecuencia real (paso de 0,093 Hz). */
double dds_configurar(double frec, dds_forma_t forma, int habilitado);
/* Amplitud: posición del potenciómetro digital, 0..255 */
void   dds_amplitud(uint8_t paso);

#endif
