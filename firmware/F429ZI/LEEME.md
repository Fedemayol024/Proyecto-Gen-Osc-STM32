# Firmware para NUCLEO-F429ZI

Es el mismo código que el de la F767ZI. `placa.h` detecta el micro al compilar y ajusta las diferencias: caché de datos, disparo del ADC, registro de reloj de los timers y tamaño del buffer del osciloscopio. Los pines son los mismos en las dos placas.

## Crear el proyecto en STM32CubeIDE

1. **File → New → STM32 Project → Board Selector** → **NUCLEO-F429ZI** → *Next*.
2. Nombre: `Instrumento_F429`, lenguaje C → *Finish*. A **"Initialize all peripherals with their default Mode?"** respondé **Yes**.

### Configurar el `.ioc`
1. **Connectivity → ETH** → Mode: **Disable**.
2. **Connectivity → USB_OTG_FS** → Mode: **Device_Only**.
3. **Middleware → USB_DEVICE** → *Class For FS IP*: **Communication Device Class (Virtual Port Com)**.
4. **Clock Configuration** → en *HCLK* escribí **168** y Enter. Si aparece *Resolve Clock Issues*, aceptalo.
   - Con 168 MHz el reloj del USB queda en **48 MHz exactos**. Con 180 MHz el USB no funciona.
5. **No actives** DAC, ADC1/ADC2, TIM1, TIM2, TIM5, TIM6, TIM8 ni sus DMA: los configura el código del instrumento. Dejá sin asignar los pines PA0, PA3, PA4, PA5, PC0, PE8 y PE9.
6. *SYS → Timebase Source*: **SysTick**.
7. Guardá con **Ctrl+S** y generá el código.

### Agregar los archivos
Copiá los `.h` de `Core/Inc` de esta carpeta a **Core/Inc** del proyecto, y los `.c` de `Core/Src` a **Core/Src**. Son 8 `.h` (incluido `placa.h`) y 7 `.c`.

### Agregados en `Core/Src/main.c`
```c
/* USER CODE BEGIN Includes */
#include "instrumento.h"
/* USER CODE END Includes */
...
  /* USER CODE BEGIN 2 */
  instrumento_iniciar();
  /* USER CODE END 2 */
...
    /* USER CODE BEGIN 3 */
    instrumento_lazo();
  }
  /* USER CODE END 3 */
```

### Agregados en `USB_DEVICE/App/usbd_cdc_if.c`
```c
/* USER CODE BEGIN INCLUDE */
#include "instrumento.h"
/* USER CODE END INCLUDE */
```
En `CDC_Receive_FS`, entre `USER CODE BEGIN 6` y `END 6`:
```c
  instrumento_usb_rx(Buf, *Len);
  return (USBD_OK);
```
Recomendado: en `USER CODE BEGIN PRIVATE_VARIABLES` declarar
`static uint8_t lineCoding[7] = {0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08};`
y completar los dos casos **que ya existen** en `CDC_Control_FS`. No hay que agregar casos nuevos, porque daría "duplicate case value":
```c
    case CDC_SET_LINE_CODING:
      memcpy(lineCoding, pbuf, 7);
    break;

    case CDC_GET_LINE_CODING:
      memcpy(pbuf, lineCoding, 7);
    break;
```

### Cargar y conectar
Cargá con *Run* por el USB del ST-LINK. Después conectá un **segundo cable** al USB **USER** (CN13). En la app elegí **NUCLEO-F429ZI** al abrir.

## Si la app dice «La placa no respondió»

El puerto COM aparece en Windows, pero la placa no contesta. Casi siempre falta alguno de los agregados de arriba: los archivos del instrumento están en el proyecto, pero nadie los llama, y el compilador los descarta sin avisar.

| Síntoma | Causa | Arreglo |
|---|---|---|
| El LED azul LD2 **no** parpadea | Falta `instrumento_iniciar()` / `instrumento_lazo()` en `main.c` | Agregarlos (y el `#include "instrumento.h"`) en los bloques USER CODE |
| LD2 parpadea, pero no hay respuesta | `CDC_Receive_FS` todavía tiene el código de CubeMX (`USBD_CDC_SetRxBuffer` + `USBD_CDC_ReceivePacket`) | Reemplazarlo por `instrumento_usb_rx(Buf, *Len); return (USBD_OK);` |
| No aparece ningún puerto COM | Cable en el ST-LINK en lugar del USB USER (CN13), o HCLK distinto de 168 MHz | Usar CN13; poner HCLK = 168 en *Clock Configuration* |

Para ver qué contesta la placa: `python diag_puerto.py COMx` desde la carpeta `app`.

## Diferencias con la F767ZI

| | F767ZI | F429ZI |
|---|---|---|
| Osciloscopio | hasta ~1,6 MS/s | hasta ~1,2 MS/s (ADC a 21 MHz) |
| Buffer de captura | 32768 muestras | 16384 muestras (la SRAM es de 192 KB) |
| Ventana máxima | 8192 puntos | 8192 puntos (busca el disparo en menos tiempo extra) |
| Generador, frecuencímetro, PWM | iguales | iguales |
