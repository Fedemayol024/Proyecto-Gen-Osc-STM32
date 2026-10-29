# Reglas del proyecto

- Cada cambio que llegue a `main` se anota en `CHANGELOG.md`, en la sección **[Sin publicar]**, con las secciones Nuevo / Mejorado / Corregido / Quitado / Firmware / Hardware / Pendiente de probar.
- Al publicar una versión, las entradas de [Sin publicar] pasan a `## [0.X.Y beta] · AAAA-MM-DD`, y el número se actualiza en `VERSION` (`app/main.py`), en `INSTR_VERSION` (los `instrumento.h` de las dos placas) y en `pruebas/nucleo_simulado.py`.
- Numeración: PARCHE para correcciones y mejoras chicas; MENOR para funciones grandes o cambios del protocolo USB.
- Las notas se escriben en castellano rioplatense, pensando en quien usa la app y no en el código.
