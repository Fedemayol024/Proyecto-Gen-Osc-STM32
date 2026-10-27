# Instrumento NUCLEO-F767ZI / NUCLEO-F429ZI: osciloscopio, generador, Bode, frecuencímetro y PWM

Una sola app de PC y una placa **NUCLEO-F767ZI** o **NUCLEO-F429ZI** forman un pequeño laboratorio por USB. Las dos placas usan los mismos pines; al abrir la app se elige con cuál trabajar.

| Función | Qué hace | Pines |
|---|---|---|
| **Generador de 2 canales** | DAC de 12 bits a 1 MS/s, hasta ~100 kHz útiles. Formas: seno, cuadrada (ciclo útil), triangular (simetría), sierra, continua, ruido y arbitraria (desde CSV). Fase relativa exacta entre canales. Modulación **AM/FM** y **barrido** lineal o logarítmico. | PA4 (D24), PA5 (D13) |
| **Osciloscopio de 2 canales** | ADC de 12 bits, los dos canales muestreados en el mismo instante, hasta ~1,6 MS/s. Disparo por flanco y nivel (Auto / Normal / Único), mediciones automáticas, cursores, **persistencia tipo fósforo**, **FFT con análisis de picos** (THD, SNR, eliminación del piso de ruido), modo **XY**, autoset, exportación a CSV y PNG. | PA3 (A0), PC0 (A1) |
| **Analizador de Bode** | Barre la frecuencia con el generador y mide ganancia (dB) y fase (°) del circuito. Detecta la frecuencia de corte a −3 dB. | Generador + osciloscopio |
| **Frecuencímetro** | Conteo de flancos (hasta decenas de MHz) o método recíproco (frecuencias bajas con muchas cifras). Elige el método solo. | PA0 (D32) |
| **PWM complementario** | Hasta decenas de MHz, ciclo útil y **tiempo muerto** ajustables (ns), para puentes H e inversores. | PE9 (D6), PE8 (D42) |

> Todo lo de arriba anda con la placa sola usando los pines directos: entradas de 0 a 3,3 V y salidas de 0,2 a 3,1 V. El hardware adicional (carpeta `hardware`) agrega salidas de ±5 V, entradas de ±10 V / ±1 V con 1 MΩ y protección, y una entrada protegida para el frecuencímetro.

## Contenido

```
firmware/F767ZI/Proyecto_Gen_Osc/              → proyecto de STM32CubeIDE completo para la F767ZI
firmware/F429ZI/Core/Inc, Core/Src             → archivos para el proyecto de la F429ZI (ver su LEEME)
app/main.py (+ otros .py)                      → programa de PC
app/build_exe.bat                              → crea Instrumento.exe
hardware/hoja1_salidas.png                     → salidas ±5 V del generador
hardware/hoja2_entradas.png                    → entradas del osciloscopio
hardware/hoja3_frecuencimetro_pwm_alimentacion.png
pruebas/                                       → Nucleo simulado y pruebas automáticas de la app
```

---

## 1. Firmware en STM32CubeIDE

Cada placa tiene su carpeta con su propia guía:

| Placa | Carpeta | Qué hay |
|---|---|---|
| NUCLEO-F767ZI | `firmware/F767ZI` | El proyecto de CubeIDE listo: **File → Import → Existing Projects into Workspace**. |
| NUCLEO-F429ZI | `firmware/F429ZI` | Los archivos del instrumento y los pasos para crear el proyecto (HCLK a **168 MHz**). |

El código del instrumento es el mismo en las dos. `placa.h` detecta el micro al compilar y resuelve las diferencias: caché de datos, disparo del ADC, registro de reloj de los timers y tamaño del buffer del osciloscopio (el F429 tiene 192 KB de RAM y captura hasta 16384 muestras en lugar de 32768).

Los pasos de abajo sirven para crear el proyecto desde cero. Para la F429ZI, seguí `firmware/F429ZI/LEEME.md`, que tiene sus diferencias.

El código del instrumento configura sus periféricos (DAC, ADC, DMA y timers) directamente en los registros. Por eso, en CubeMX **solo hay que activar el USB**. El firmware se compiló contra la HAL F7 y la librería USB oficiales de ST, sin errores ni advertencias.

### 1.1 Crear el proyecto
1. **File → New → STM32 Project → Board Selector** → elegí **NUCLEO-F767ZI** → *Next*.
2. Nombre: `Instrumento`, lenguaje C → *Finish*. Cuando pregunte **"Initialize all peripherals with their default Mode?"** → **Yes**.

### 1.2 Configurar el .ioc
1. **Connectivity → ETH** → Mode: **Disable**. El Ethernet no se usa y así no reserva pines.
2. **Connectivity → USB_OTG_FS** → Mode: **Device_Only** (suele venir así por defecto).
3. **Middleware and Software Packs → USB_DEVICE** → *Class For FS IP*: **Communication Device Class (Virtual Port Com)**.
4. **Clock Configuration** → en *HCLK* escribí **216** y Enter. Si aparece *Resolve Clock Issues*, aceptalo. Verificá que el reloj de 48 MHz (USB) quede en 48.
5. **No actives** en CubeMX DAC, ADC1/ADC2, TIM1, TIM2, TIM5, TIM6, TIM8 ni sus DMA: los configura el código del instrumento. Los pines PA0, PA3, PA4, PA5, PC0, PE8 y PE9 tienen que quedar sin asignar.
6. *System Core → SYS → Timebase Source*: dejalo en **SysTick**. No uses TIM6 ni FreeRTOS.
7. Guardá con **Ctrl+S** y generá el código.

> La D-Cache del Cortex-M7 (*System Core → CORTEX_M7*) puede estar activada o no: el código hace el mantenimiento de caché solo.

### 1.3 Agregar los archivos
Copiá los `.h` de `Core/Inc` y los `.c` de `Core/Src` de la carpeta de tu placa (en la F767ZI están dentro de `Proyecto_Gen_Osc`) a las carpetas **Core/Inc** y **Core/Src** del proyecto. Son 7 `.h` (incluido `placa.h`) y 6 `.c`. Podés arrastrarlos al *Project Explorer* y elegir *Copy files*.

### 1.4 Tres agregados en `Core/Src/main.c`
```c
/* USER CODE BEGIN Includes */
#include "instrumento.h"
/* USER CODE END Includes */
...
  /* USER CODE BEGIN 2 */
  instrumento_iniciar();
  /* USER CODE END 2 */
...
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    instrumento_lazo();
  }
  /* USER CODE END 3 */
```

### 1.5 Dos agregados en `USB_DEVICE/App/usbd_cdc_if.c`
```c
/* USER CODE BEGIN INCLUDE */
#include "instrumento.h"
/* USER CODE END INCLUDE */
```
Reemplazá el contenido de `CDC_Receive_FS` entre `USER CODE BEGIN 6` y `END 6` por:
```c
  /* USER CODE BEGIN 6 */
  instrumento_usb_rx(Buf, *Len);   /* copia los datos y rearma la recepción */
  return (USBD_OK);
  /* USER CODE END 6 */
```
Opcional, pero recomendado para que Windows lea bien la configuración del puerto: en `CDC_Control_FS`, dentro de `USER CODE BEGIN PRIVATE_VARIABLES` declarar
`static uint8_t lineCoding[7] = {0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08};` y completar los casos **que ya existen** en el `switch` (no agregar casos nuevos, porque daría "duplicate case value"):
```c
    case CDC_SET_LINE_CODING:
      memcpy(lineCoding, pbuf, 7);
    break;

    case CDC_GET_LINE_CODING:
      memcpy(pbuf, lineCoding, 7);
    break;
```

### 1.6 Compilar y cargar
1. Compilá (martillo) y cargá con *Run* usando el USB del **ST-LINK** (CN1, el de arriba).
2. Conectá **un segundo cable** al USB **USER** (CN13, abajo, al lado del Ethernet). Windows va a mostrar un nuevo "Dispositivo serie USB (COMx)". Ese es el puerto del instrumento.
3. El LED azul LD2 parpadea (4 veces por segundo) mientras el programa está corriendo. Los LED verde y rojo quedan apagados.
4. **Watchdog:** el firmware arranca el watchdog independiente (IWDG) con 2 s. Si el programa se colgara, la placa se reinicia sola y la app se reconecta y avisa. Mientras depurás en CubeIDE y frenás en un breakpoint, el watchdog queda congelado, así que no reinicia. No hace falta activar nada en el `.ioc`: se configura desde el código.

---

## 2. App de PC

```
cd app
python -m pip install -r requirements.txt
python main.py
```
Para crear el `.exe`, hacé doble clic en `app/build_exe.bat`. Necesita Python 3.10 o superior instalado desde python.org con *Add to PATH*. El ejecutable queda en `app\dist\Instrumento.exe`. Es un solo archivo de unos 80–100 MB y tarda unos segundos en abrir.

**Uso rápido**
0. **Al abrir, elegí la placa** (NUCLEO-F767ZI o NUCLEO-F429ZI). Si marcás *Recordar mi elección*, no vuelve a preguntar. Se cambia después con el botón de la placa en la barra de arriba. Cada placa guarda su propia configuración y calibración. Si conectás una placa distinta de la elegida, la app lo detecta y ofrece cambiar.
1. Elegí el puerto marcado como *"Instrumento (USB del Nucleo)"* → **Conectar**. El del ST-LINK aparece marcado como "no es este".
2. **Generador:** cada canal tiene su salida, forma, frecuencia o período (aceptan `2k`, `2,5 kHz`, `20 ms`…), amplitud, offset, ciclo útil o simetría, fase, modulación y barrido. Los cambios se mandan solos. La rueda del mouse sobre un campo ajusta la segunda cifra.
3. **Osciloscopio:**
   - **RUN/STOP**, **Único** y **Autoset**.
   - Tiempo/div, V/div y posición. La línea naranja de disparo se puede arrastrar.
   - En **Entrada** elegí "Placa ±10 V", "Placa ±1 V (×10)" (tiene que coincidir con la llave S2/S4 de la placa) o "Pin directo".
   - **Pantalla → Persistencia** (1 s, 2 s, 3 s o Infinita): deja el rastro de los trazos anteriores como el fósforo de un osciloscopio analógico. Un transitorio que aparece una sola vez queda marcado ese tiempo, o para siempre en *Infinita*; lo que se repite brilla más. *Borrar* lo limpia, y se borra solo al cambiar escalas.
   - **Pantalla → Espectro (FFT) → Análisis de picos…** abre una ventana que se actualiza en vivo:
     - *Procesamiento:* ventana (Blackman-Harris, Flat-top, Hann, Hamming, Rectangular), **promediado** de 4 a 64 cuadros (el ruido se vuelve parejo y desaparecen los micropicos) y **Eliminar piso de ruido** (suave o fuerte): estima el piso con una mediana móvil y lo resta, así quedan solo las componentes reales.
     - *Detección:* umbral absoluto (también se arrastra la línea punteada del gráfico), cuánto tiene que sobresalir del piso, separación mínima y máximo de picos. Los picos se marcan y numeran en el gráfico.
     - *Mediciones:* fundamental, THD, SNR, SINAD, ENOB, piso y densidad de ruido, RBW, y una tabla de picos con nivel (dBV y V eficaces), dBc y número de armónico. Se exporta a CSV.
4. **Bode:** conectá Generador CH1 → entrada del circuito y IN1, y la salida del circuito → IN2. Elegí el rango y tocá *Iniciar barrido*.
5. **Frecuencímetro y PWM:** lectura grande con el método usado. El PWM muestra los valores reales obtenidos.
6. **Calibración** (una vez):
   - **Salidas:** con multímetro, dos puntos por canal.
   - **Entradas:** automática, conectando OUT1→IN1 y OUT2→IN2. También hay un "cero" con las entradas a GND.
7. **Tamaño de la interfaz:** botones **A− / A+** arriba a la derecha (o **Ctrl +**, **Ctrl −**, **Ctrl 0**, o **Ctrl + rueda del mouse**). Agranda o achica todo, de 80 % a 200 %, y se recuerda para la próxima vez.
8. **Placa:** capacidades y límites de la placa elegida (con los valores medidos en vivo al conectar), un dibujo de la placa con la ubicación de cada pin que usa el instrumento y diagramas de conexión para los usos típicos (prueba rápida, Bode, señal externa, frecuencímetro y PWM).

Las calibraciones y los ajustes se guardan en `%APPDATA%\InstrumentoF767\`: `config.json` para la F767ZI y `config_F429.json` para la F429ZI. La placa elegida se guarda en `preferencias.json`.

---

## 3. Hardware adicional

### Hoja 1: salidas ±5 V (U1 = TL072 con ±12 V)
`Vout = 3,909·Vdac − 6,6 V`. Con el DAC dentro de su zona lineal (0,41 a 2,97 V) cubre ±5 V con pasos de ~3,2 mV. La referencia del corrimiento es el mismo 3,3 V del DAC: si el 3,3 V varía, el cero no se mueve. R1-C1 filtran los escalones del DAC, y la resistencia de 47 Ω protege contra cortos.

### Hoja 2: entradas del osciloscopio (U2 = MCP6024 con 3,3 V)
- **Atenuador de 1 MΩ:** el nodo X queda en `1,65 V + 0,150·Vin`, así que ±10 V entran en 0,15–3,15 V.
- **S2 cerrada (×10):** ganancia 10,1 alrededor de 1,65 V, rango ±1 V con pasos de ~0,5 mV.
- **S1:** acople AC o DC.
- **Protección:** BAV99 al nodo X. Como el operacional se alimenta con 3,3 V, al ADC nunca le llega más que eso.
- **Compensación:** el trimmer CT1 (2–10 pF) compensa el atenuador como una punta de osciloscopio. Ajustalo con el PWM a 1 kHz y 50 % hasta ver una cuadrada con flancos rectos.
- **Puntas:** con punta ×10 (elegir "×10" en la app), hasta ±100 V.

### Hoja 3: frecuencímetro, PWM y alimentación
- **Frecuencímetro:** entrada protegida con R40 y BAV99.
- **PWM:** salidas con 100 Ω en serie.
- **Alimentación ±12 V:** módulo DC-DC A0512S-1W desde el 5 V del Nucleo. También sirve una fuente partida, o dos baterías de 9 V.

### Lista de materiales

| Ref. | Valor | Cant. | Notas |
|---|---|---|---|
| U1 | TL072 (DIP-8) | 1 | o TL082 / NE5532 |
| U2 | MCP6024 (DIP-14) | 1 | rail-to-rail, 10 MHz (alternativa: OPA4350) |
| DC-DC | A0512S-1W (5 V → ±12 V) | 1 | o fuente partida / 2 × 9 V |
| R1, R6 | 330 Ω | 2 | |
| R2, R7 | 30 kΩ 1 % | 2 | |
| R3, R8 | 15 kΩ 1 % | 2 | |
| R4, R9 | 33 kΩ 1 % | 2 | |
| R5, R10 | 47 Ω | 2 | |
| R11, R21 | 1 MΩ 1 % | 2 | |
| R12, R22 | 300 kΩ 1 % | 2 | |
| R13, R23 | 430 kΩ 1 % | 2 | |
| R14, R24 | 9,1 kΩ 1 % | 2 | |
| R15, R25 | 1 kΩ 1 % | 2 | |
| R16, R26, R50, R51 | 100 Ω | 4 | |
| R30, R31 | 10 kΩ | 2 | |
| R40 | 1 kΩ | 1 | |
| R41 | 100 kΩ | 1 | |
| C1, C2 | 1 nF cerámico | 2 | |
| C11, C21 | 100 nF / 250 V | 2 | acople AC |
| C12, C22 | 22 pF NP0 | 2 | |
| C13, C23 | 470 pF NP0 | 2 | |
| CT1, CT2 | trimmer 2–10 pF | 2 | |
| C30 | 1 µF | 1 | |
| C60–C62 | 10 µF 25 V | 3 | |
| — | 100 nF cerámico | 4 | desacople de U1 (×2) y U2 |
| D11, D21, D40 | BAV99 | 3 | doble diodo de baja capacidad |
| S1–S4 | llave 1 polo | 4 | AC/DC y ×10 |
| — | BNC hembra | 5 | OUT1, OUT2, IN1, IN2, FREC |

Las resistencias del 5 % también sirven: la calibración compensa el error.

---

## 4. Protocolo USB (por si querés usarlo desde otro programa)

Son líneas de texto terminadas en `\n`.

| Comando | Respuesta |
|---|---|
| `ID?` / `INFO?` | `INSTR-F767 v1.0` / `INFO gen_fs=… osc_fsmax=… wdg_ms=2000 reinicio=watchdog\|energia\|boton\|software\|otro` |
| `GTBL c 4096 suma` + 8192 bytes | `OK GTBL c` (tabla uint16 little-endian; la suma es la de los códigos) |
| `GSET c frec fase hab reposo` | `OK GSET c frec_real` |
| `GMOD c NO\|AM\|FM p fmod centro` | `OK GMOD c fmod_real` |
| `GSWP c NO\|LIN\|LOG f1 f2 t` | `OK GSWP c` |
| `GSYNC` | `OK GSYNC` |
| `CAP n pre fs fuente nivel flanco hist` | `DATA n pre fs disparado` + 4·n bytes (CH2<<16 \| CH1) |
| `CAPX` | `OK CAPX` |
| `FCNT ms continuo` | `FREQ f metodo flancos ms` |
| `PWM frec ciclo tm_ns hab` | `OK PWM frec_real ciclo_real tm_real` |

## 5. Límites y consejos
- **Si la placa se cuelga o se reinicia:** el watchdog la reinicia sola en 2 s. La app detecta que se cortó el USB, la busca durante 20 s, se reconecta, vuelve a mandar la configuración del generador y avisa en la barra de estado si el reinicio fue por el watchdog. En la pestaña **Placa** se ve la causa del último reinicio. Durante la reconexión el botón dice *Cancelar*.
- **Rangos de los pines directos:** las entradas del ADC aceptan **solo 0 a 3,3 V**. Para cualquier otra señal usá la etapa de entrada.
- **Ancho de banda:** el osciloscopio llega a ~1,6 MS/s, así que hasta ~150–200 kHz se ven bien. El generador, hasta ~100 kHz.
- **Bode:** queda bien de unos pocos Hz hasta ~100 kHz. Las frecuencias bajas tardan más, porque espera el régimen permanente y captura al menos 8 períodos.
- **Señales lentas:** con bases de tiempo de 50 ms/div o más, en modo Auto se captura sin buscar disparo para no esperar de más.
- **Mantenimiento de la caché:** si en el futuro agregás tus propios buffers DMA, usá `cache_limpiar` y `cache_invalidar`.
