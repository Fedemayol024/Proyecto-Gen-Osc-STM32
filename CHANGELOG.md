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
- **Pestaña Placa:** esquema «Módulo AD9833» en Conexiones (los 6 cables de CN8 y la salida PGA), sus pines marcados en el dibujo de la placa (D45, D47, D48, D49) y una sección con sus capacidades.

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
- `osciloscopio.c`: `osc_abortar()` corta los pedidos de DMA del ADC, vacía los datos, borra los flags y reinicia ADC1/ADC2. Nuevo `osc_vigilar()` (en el lazo principal) para rearmar capturas trabadas. Mismo código en las dos placas. **Hay que recompilar y cargar el firmware** en la F767ZI y en la F429ZI (para la F429 copiar `osciloscopio.c/.h` e `instrumento.c`).
- Nuevo `ad9833.c/.h` (en las dos placas): SPI por software en PC10 (CLK), PC12 (DAT), PD2 (FSY) y PG2 (CS). Comandos `DDS frec forma hab` y `DDSA paso`. `INFO?` agrega `dds_mclk=`. Al arrancar, el módulo queda apagado. Las palabras SPI se verificaron contra la hoja de datos simulando los pines en la PC.
- **Hay que copiar `ad9833.c/.h` e `instrumento.c` al proyecto** (F767ZI y F429ZI) y recompilar.

### Hardware
- Diagrama `hardware/ad9833_conexion.png` actualizado con lo que confirmaron las fotos del módulo (AD9833 + MCP41010 + AD8051): alimentar con 3,3 V; VOUT es la salida directa y PGA la amplificada.

### Pendiente de probar
- Single y Autoset con la placa real, con el firmware viejo (ya no debería congelarse, por el arreglo de la app) y con el nuevo.
- Opciones gráficas en la notebook del compañero y en una pantalla con el escalado de Windows al 125 % / 150 %.
- Primera prueba real del módulo: frecuencia, las tres formas y el rango de amplitud en VOUT y en PGA, para calibrar los volts.
- Bode con el AD9833 por encima de 100 kHz (necesita muestreo coherente; queda para después).

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
