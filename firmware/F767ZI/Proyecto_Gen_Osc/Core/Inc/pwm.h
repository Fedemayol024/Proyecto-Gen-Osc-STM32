/*
 * pwm.h - Salida PWM complementaria con tiempo muerto (TIM1)
 *   PWM  -> PE9 (D6)  = TIM1_CH1
 *   PWMN -> PE8 (D42) = TIM1_CH1N (complementaria)
 * Señales lógicas de 3,3 V. Sirve para probar etapas de potencia (puente H,
 * inversores) a través de un driver de compuertas, o como generador de pulsos.
 */
#ifndef PWM_H
#define PWM_H

#include <stdint.h>

void pwm_iniciar(void);
/* frec en Hz, ciclo en % (0..100), tiempo muerto en ns. Devuelve los
 * valores reales que se pudieron obtener. */
void pwm_configurar(double frec, double ciclo, double tm_ns, int habilitado,
                    double *frec_real, double *ciclo_real, double *tm_real);

#endif
