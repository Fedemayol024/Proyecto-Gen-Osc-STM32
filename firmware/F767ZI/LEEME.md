# Firmware para NUCLEO-F767ZI

`Proyecto_Gen_Osc` es el proyecto completo de STM32CubeIDE, listo para compilar.

Para abrirlo: **File → Import → General → Existing Projects into Workspace** y elegí esta carpeta (`firmware/F767ZI`).

> Si ya lo tenías importado desde la raíz del repositorio, borralo del workspace con *Delete* **sin** marcar "Delete project contents on disk" e importalo de nuevo desde esta ubicación.

El código del instrumento está en `Proyecto_Gen_Osc/Core/Inc` y `Core/Src`. Es el mismo que el de la F429ZI: `placa.h` resuelve las diferencias entre las dos placas.
