# Notas de versión

Registro de cambios del instrumento (app de PC + firmware de la NUCLEO-F767ZI / NUCLEO-F429ZI).

**Cómo se numera:** `0.MENOR.PARCHE beta`
- **PARCHE** (0.8.18 → 0.8.19): correcciones y mejoras chicas que no cambian el protocolo USB.
- **MENOR** (0.8.x → 0.9.0): funciones nuevas grandes o cambios en el protocolo. La app avisa si el firmware de la placa es de otra serie menor.
- **1.0.0**: cuando todo esté probado en hardware real (placa + hojas 1 a 3 + AD9833).

La app (`VERSION` en `app/main.py`) y el firmware (`INSTR_VERSION` en `instrumento.h`) llevan siempre el mismo número.

**Secciones de cada versión:** Nuevo · Mejorado · Corregido · Quitado · Firmware · Hardware · Pendiente de probar.

> Las versiones anteriores a la 0.8.18 se reconstruyeron después, a partir del historial de commits. Los números que faltan (0.8.3, 0.8.5, etc.) fueron compilaciones internas sin cambios para el usuario.

---

## [Sin publicar]

_Acá se anotan los cambios a medida que se hacen; al subir de versión se pasan a una sección con número y fecha._

### Nuevo
- **Módulo AD9833 (generador DDS externo).** Panel «Módulo AD9833» en la pestaña Generador: encender y apagar, forma (seno, triangular o cuadrada), frecuencia de 0,1 Hz a 12,5 MHz con paso de 0,093 Hz, y amplitud con el potenciómetro digital MCP41010 del módulo. La configuración se guarda y se reenvía al reconectar. Muestra la frecuencia confirmada por la placa.
- Si el firmware de la placa no maneja el AD9833, la app no le manda esos comandos y avisa en el panel que hay que cargar el firmware nuevo.
- **AD9833 ampliado (para probar):**
  - **Fase** de la salida (pasos de 0,088°) y forma **cuadrada f/2**.
  - **Modulaciones** hechas por el firmware: barrido lineal o logarítmico (cambia cada 0,5 ms sin saltos de fase), **FSK** y **PSK** (alterna los dos registros de frecuencia o de fase del chip, hasta 5000 símbolos/s), **ráfagas** de N ciclos que arrancan en fase 0, y **AM** lenta moviendo el potenciómetro (hasta 200 Hz, 256 pasos).
  - **Calibrar amplitud…** es un asistente paso a paso: la app pone la salida en 0, 25, 50, 75 y 100 % (seno de 1 kHz), vos cargás el Vpp y la tensión media que medís y «Continuar» pasa al siguiente. Se puede volver, saltear un punto y corregir todo en el resumen final. Acepta los valores como los muestra el osciloscopio («906,25mV», «625,00 mV», «1,48 V», «1.48»). Al terminar o cancelar, el AD9833 vuelve a como estaba.
  - **Calibración automática con CH1** (otra opción dentro del mismo asistente): uniendo la salida PGA con A0, la app pone cada amplitud, espera a que se asiente, captura CH1 a 200 kS/s y calcula el Vpp con un ajuste senoidal (no lo engañan el ruido ni los picos sueltos) y la tensión media sobre períodos completos. Pasa sola por los cinco puntos (~4 s), avisa si la señal se recortó en el ADC o si no llega, y deja el resumen para revisar y guardar. Mientras mide, el osciloscopio queda en pausa y después vuelve a RUN. Con la calibración, la amplitud se puede escribir en Vpp, se muestra entre qué tensiones va la salida y se avisa si no entra en los pines directos (0–3,3 V).
  - **Medir reloj…**: uniendo VOUT con D32, el frecuencímetro mide una cuadrada de 1 MHz y corrige el error del cristal de 25 MHz. Queda guardado y se aplica en todas las frecuencias.
  - **Amplitud en Vpp:** con la calibración hecha, la amplitud se elige directamente en Vpp, de 0 V hasta lo medido a 100 % (para este selector el 0 % cuenta como 0 V; la tabla conserva lo medido). Queda en el paso más cercano del potenciómetro (256 pasos) y muestra cuál es. Sin calibrar, se sigue eligiendo en %.
  - **La fase solo aparece donde se nota:** en PSK («Fase 1») y en ráfagas («Fase de arranque»). Con una sola salida suelta, cambiar la fase no se ve (no hay contra qué compararla), y eso confundía.
  - Con el firmware anterior del AD9833 (solo frecuencia, forma y amplitud), la app no manda los comandos nuevos y avisa.
- **Pestaña Placa:** esquema «Módulo AD9833» en Conexiones (los 6 cables de CN8 y la salida PGA), sus pines marcados en el dibujo de la placa (D45, D47, D48, D49) y una sección con sus capacidades.
- **Dibujo de pines más claro:** cada cable de rótulo va por su propio carril, sin cruzarse ni pisarse con los demás. Los pines de la columna de adentro salen por el hueco entre filas, así no pasan por encima del pin de al lado (por ejemplo GND y FSY en CN8).
- **Resaltado al pasar el mouse:** en Placa → Pines, al pasar el mouse por un rótulo o por su pin, ese cable se marca más grueso, con un halo y un anillo en el pin, y los demás se atenúan. Así se sigue fácil a dónde va cada uno.

- **Bode con el AD9833, hasta 10 MHz.** En la pestaña Bode hay un selector de **Fuente**: el generador interno (hasta ~100 kHz, como antes) o el **Módulo AD9833**. Con el AD9833:
  - hasta ~600 kHz mide directo; más arriba, **submuestreando**: elige la frecuencia de muestreo para que la señal aparezca plegada a ~fs/4 (lejos de la continua y de fs/2) y, como CH1 y CH2 se muestrean en el mismo instante, el cociente salida/entrada conserva la ganancia y la fase reales (con el alias «dado vuelta», corrige el signo de la fase);
  - la frecuencia se **estima de los datos** de CH1 (pico de la FFT + máximo del ajuste senoidal), así un error de algunas ppm del cristal del módulo no desfasa el ajuste;
  - usa la amplitud del panel AD9833 y, al terminar, vuelve a dejar el módulo como estaba (con su modulación);
  - mantiene el promedio adaptativo cuando la salida es chica.
  - Verificado: con datos sintéticos (RC de 100 kHz, cristal corrido 20 ppm, ruido y cuantización del ADC) el error es menor a 0,1 dB y 1° de 1 kHz a 9 MHz; con el Nucleo simulado (que además filtra los dos canales como el muestreo del ADC), barrido de 1 kHz a 5 MHz en ~3 s con error máximo de 0,08 dB / 1,1° (F767) y 0,17 dB / 1,4° (F429).
- **Placa → Conexiones:** esquema «Bode con el AD9833 (hasta MHz)».

### Corregido
- **El trazo se congelaba al tocar Single o Autoset** (en las dos placas) y solo volvía reconectando la placa. Esos dos botones pedían una captura nueva mientras la anterior todavía estaba en curso, y el firmware la cortaba a la mitad: el ADC dual quedaba en *overrun* y no volvía a entregar datos. Ahora:
  - la app espera a que llegue la captura en camino antes de arrancar el Single o el Autoset (como ya hacía RUN);
  - el firmware, al cortar una captura, reinicia bien el ADC y el DMA;
  - si una captura tarda bastante más de lo que debería, el firmware la vuelve a armar sola en lugar de quedarse esperando. `STAT?` informa cuántas veces pasó (`osc_rein=`).
- **En notebooks la ventana no entraba en la pantalla.** Al 100 % necesitaba 1378 px de ancho, por la pestaña Placa y por el texto de conexión de la barra de arriba. Ahora necesita unos 880 px: la pestaña Placa se acomoda y desplaza, y el texto de conexión se recorta con «…» (completo en el tooltip). Al abrir, la ventana se ajusta a la pantalla.
- **Al agrandar la interfaz, la ventana se salía del monitor** (crecía hacia la derecha). Ahora, después de cambiar la resolución, se vuelve a acomodar dentro de la pantalla con su tamaño nuevo.

### Mejorado
- **Opciones gráficas (⚙)** en lugar de los botones A− / 100 % / A+: menú con la resolución de la interfaz (1280×720 a 3840×2160). Por defecto es **Automática**, la misma de la pantalla. Una resolución más chica agranda todo y una más grande hace entrar más, como en los juegos.
- La app ya no pasa todos los eventos de la ventana por Python para el atajo Ctrl + rueda (que se quitó): se aliviana el dibujo.
- Single avisa «esperando el disparo… (tocá STOP para cancelar)» y «captura lista».

### Firmware
- `ad9833.c`: fase (PHASE0/PHASE1), cuadrada f/2, corrección de reloj y modulaciones (barrido, FSK, PSK, ráfaga, AM) avanzadas desde el lazo principal con el contador de ciclos del núcleo (DWT). Comandos `DDSF`, `DDSCLK` y `DDSMOD`; `INFO?` agrega `dds_mod=1`. Probado en la PC simulando los pines y el contador: palabras SPI, tiempos de FSK/PSK y ráfaga, rango del barrido y del potenciómetro en AM.
- `osciloscopio.c`: `osc_abortar()` corta los pedidos de DMA del ADC, vacía los datos, borra los flags y reinicia ADC1/ADC2. Nuevo `osc_vigilar()` (en el lazo principal) para rearmar capturas trabadas. Mismo código en las dos placas. **Hay que recompilar y cargar el firmware** en la F767ZI y en la F429ZI (para la F429 copiar `osciloscopio.c/.h` e `instrumento.c`).
- Nuevo `ad9833.c/.h` (en las dos placas): SPI por software en PC10 (CLK), PC12 (DAT), PD2 (FSY) y PG2 (CS). Comandos `DDS frec forma hab` y `DDSA paso`. `INFO?` agrega `dds_mclk=`. Al arrancar, el módulo queda apagado. Las palabras SPI se verificaron contra la hoja de datos simulando los pines en la PC.
- **Hay que copiar `ad9833.c/.h` e `instrumento.c` al proyecto** (F767ZI y F429ZI) y recompilar.

### Hardware
- Diagrama `hardware/ad9833_conexion.png` actualizado con lo que confirmaron las fotos del módulo (AD9833 + MCP41010 + AD8051): alimentar con 3,3 V; VOUT es la salida directa y PGA la amplificada.

### Pendiente de probar
- Single y Autoset con la placa real, con el firmware viejo (ya no debería congelarse, por el arreglo de la app) y con el nuevo.
- Opciones gráficas en la notebook del compañero y en una pantalla con el escalado de Windows al 125 % / 150 %.
- Primera prueba real del módulo: hecha. Seno de 5 MHz limpio, 1,48 Vpp a 80 % sobre ~2 V de continua (medido con un FNIRSI 2C53P).
- Calibración de amplitud completa (0, 25, 50, 75 y 100 %) en PGA, y una medición en VOUT.
- Cada modulación con la placa real: barrido (ver la respuesta de un filtro), FSK, PSK, ráfagas y AM.
- Medir el reloj con el frecuencímetro (VOUT → D32).
- Bode con el AD9833 en la placa real: un RC conocido (por ejemplo 1 kΩ + 1,5 nF ≈ 106 kHz) de 1 kHz a 5 MHz, comparando con la curva teórica.

---

## [0.8.19 beta] · 2026-10-29 · La F429ZI vuelve a conectar

### Nuevo
- Este archivo de notas de versión.

### Corregido
- **NUCLEO-F429ZI no se conectaba con la app** (proyecto de CubeIDE de Jorge). Los archivos del instrumento estaban copiados, pero el proyecto nunca los llamaba: faltaban `instrumento_iniciar()` e `instrumento_lazo()` en `main.c`, y `CDC_Receive_FS` (`usbd_cdc_if.c`) seguía con el código de CubeMX en lugar de `instrumento_usb_rx()`. El compilador descartaba todo el instrumento, así que la placa aparecía como puerto COM pero no contestaba. Se agregaron esas llamadas y el `lineCoding` recomendado, y se compiló sin warnings.

### Mejorado
- Cuando la placa no responde, la app dice qué revisar: el cable en CN13, el LED azul LD2 y las dos llamadas que faltan en `main.c` y `usbd_cdc_if.c`.
- `firmware/F429ZI/LEEME.md`: nueva sección «Si la app dice “La placa no respondió”» con síntomas, causas y arreglos.

### Pendiente de probar
- Recompilar y cargar en la F429ZI de Jorge y conectar con la app.

---

## [0.8.18 beta] · 2026-10-27

Primera versión con número realista (antes la app decía «1.0»).

### Nuevo
- Número de versión y etapa («0.8.18 beta») en el título de la ventana, en la barra de estado y en la respuesta `ID?` del firmware.
- Aviso al conectar si el firmware de la placa es de otra serie que la app.

## [0.8.17] · 2026-10-27 · Watchdog y reconexión

### Nuevo
- **Watchdog independiente (IWDG)** en las dos placas, de unos 2 s. Si el firmware se cuelga, la placa se reinicia sola. Mientras se depura en CubeIDE queda congelado.
- **Causa del último reinicio** (watchdog, encendido, botón RESET, software u otro), informada por `INFO?` y mostrada en la pestaña Placa.
- **Reconexión automática** de la app: si se pierde el USB, reintenta durante 20 s, con un botón para cancelar.

### Firmware
- `hw_util.c/.h`: `wdg_iniciar()`, `wdg_patear()` y lectura de `RCC->CSR`.
- `INFO?` agrega `wdg_ms=` y `reinicio=`.

### Pendiente de probar
- Apretar RESET en la Nucleo con la adquisición en RUN y ver que la app se reconecte sola.

## [0.8.16] · 2026-10-27 · Fósforo, análisis FFT y zoom

### Nuevo
- **Persistencia tipo fósforo** en el osciloscopio: 1 s, 2 s, 3 s o infinita, con botón Borrar. Sirve para cazar transitorios y glitches.
- **Ventana «Análisis de picos…» de la FFT**:
  - tabla de picos con un umbral de detección que se puede arrastrar sobre el gráfico;
  - separación mínima entre picos y nivel mínimo sobre el piso de ruido;
  - ventanas Hann, Hamming, Blackman-Harris, Flat-top y Rectangular;
  - promedio de espectros;
  - **«Eliminar piso de ruido blanco»**: estima el piso con una mediana móvil y lo resta, así se ven limpios los picos reales;
  - análisis de armónicos con THD, SNR, SINAD y ENOB.
- **Zoom de la interfaz** del 80 % al 200 % (botones A− / 100 % / A+ y Ctrl+rueda o Ctrl +/−). Se guarda entre sesiones.

### Mejorado
- Tablas y textos escalan junto con el zoom, incluidos los dibujos de la pestaña Placa.

## [0.8.15] · 2026-10-27

### Hardware
- Diagrama de conexión del módulo **AD9833** por SPI3 en el conector CN8 (`hardware/ad9833_conexion.png`). El firmware todavía no controla el módulo.

## [0.8.14] · 2026-10-27 · Seguridad de las entradas

### Quitado
- Modo **«Tiempo equivalente»** del osciloscopio. Necesitaba unir la salida PWM con una entrada analógica, y esa conexión podía dañar el micro por error.

### Sin cambios
- Se mantiene la entrada **«Pin directo»** (0 a 3,3 V). En un momento se quitó y después se restauró.

## [0.8.12] · 2026-10-27 · Soporte para la F429ZI

### Nuevo
- **NUCLEO-F429ZI**: firmware propio por placa (`placa.h`) y un menú en la app para elegir la placa al iniciar, que se puede recordar.
- **Pestaña Placa**: capacidades y límites de cada placa, valores medidos en vivo con `INFO?`, dibujo de la Nucleo-144 con los conectores ST Zio y los pines usados, diagramas de conexión (prueba rápida, Bode, señal externa, frecuencímetro y PWM) y cuidados.
- Configuración guardada por separado para cada placa.

### Firmware
- Código de LEDs simplificado: solo el LED azul LD2 parpadea como latido; LD1 y LD3 quedan apagados.
- El modo tiempo equivalente usa el reloj de temporizador correcto en la F429.

## [0.8.9] · 2026-10-23 · Bode más preciso

### Mejorado
- **Bode**: cada punto usa la ventana completa de 8192 muestras en lugar de unas 400, sin pasar de ~0,2 s por captura.
- **Promedio adaptativo** cuando la salida del circuito es chica (pocos escalones del ADC): promedia hasta lograr ~1° de incertidumbre en la fase, con un máximo de 16 capturas o 2 s por punto. En un RC a 100 kHz (−56 dB), el error de fase bajó de ±7° a ±0,8° y el de ganancia de ±1,1 dB a ±0,13 dB.

### Corregido
- **CSV con coma decimal** y separador `;` para Excel en español. Antes 10.0001 aparecía como 100001.
- El lector de formas arbitrarias acepta coma o punto decimal y detecta solo el separador.

## [0.8.6] · 2026-10-22

### Nuevo
- Modo experimental de **tiempo equivalente** (plegado por fase) para señales repetitivas por encima de la frecuencia de muestreo. _Quitado en la 0.8.14._

## [0.8.4] · 2026-10-22 · Osciloscopio fluido

### Mejorado
- Dibujo mucho más fluido: sin antialiasing, con recorte a lo visible y diezmado de puntos.
- El desplazamiento horizontal llega hasta 2 ms/div.

## [0.8.2] · 2026-10-22

### Nuevo
- **Desplazamiento horizontal** del trazo.
- Líneas de referencia de 0 s y 0 V.
- Exportar a CSV solo lo que se ve en pantalla.

## [0.8.0] · 2026-10-22 · Primera versión en el repositorio

### Nuevo
- **App de PC** (PySide6 + pyqtgraph) con las pestañas Generador, Osciloscopio, Bode, Herramientas (frecuencímetro y PWM) y Calibración.
- **Generador de 2 canales**: DAC a 1 MS/s; seno, cuadrada, triangular, sierra, continua, ruido y arbitraria; fase entre canales; AM/FM y barrido.
- **Osciloscopio de 2 canales** simultáneos hasta ~1,6 MS/s; disparo Auto/Normal/Único; mediciones, cursores, FFT, XY, autoset y CSV/PNG.
- **Analizador de Bode** con detección de la frecuencia de corte a −3 dB.
- **Frecuencímetro** (conteo o recíproco, con elección automática) y **PWM complementario** con tiempo muerto.
- **Firmware** para la NUCLEO-F767ZI con protocolo USB CDC de texto y binario.
- **Hardware adicional**: hoja 1 (salidas ±5 V), hoja 2 (entradas ±10 V / ±1 V) y hoja 3 (frecuencímetro, PWM y alimentación).
- Nucleo simulado y pruebas automáticas.
