# Tokenizer

Herramienta para ver cuánto te queda de tu suscripción **OpenCode Go**, en una o varias máquinas, con CLI y panel web.

> Estado: en desarrollo. Esta versión incluye el lector de `opencode.db`, el cálculo de los límites de Go y el comando `status`. El servidor central, el panel web, las alertas y la sincronización entre máquinas están en la hoja de ruta.

## Cómo funciona

OpenCode Go limita el uso con tres ventanas, todas expresadas como porcentaje de tu asignación mensual:

| Ventana  | Límite                         | Reinicio                              |
| -------- | ------------------------------ | ------------------------------------- |
| 5 horas  | 20 % (desde el primer uso)     | 5 h después del primer uso            |
| Semanal  | 50 %                           | Lunes 00:00 UTC                       |
| Mensual  | 100 %                          | Inicio de cada periodo de pago        |

Cada modelo tiene un límite mensual en dólares (`go.monthly_usage` en el [catálogo de Go](https://opencode.ai/inference/go/v1/models)). Una petición consume `coste / límite del modelo` de tu asignación. Por ejemplo, $1.50 en un modelo con límite de $15 equivale al 10 %.

Tokenizer calcula ese consumo leyendo el historial local de OpenCode (`opencode.db`) en modo solo lectura. **Es una estimación**: no incluye los cambios de precio por hora punta ni los precios de contexto largo, y la cuota real siempre es la que muestra la consola de OpenCode.

## Requisitos

- Windows 10/11 (la ruta por defecto es la de Windows; otras plataformas se pueden indicar con `--db`).
- Python 3.10 o superior.

## Instalación (desarrollo)

```powershell
git clone <URL-del-repositorio>
cd tokenizer
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Uso

```powershell
tokenizer status
tokenizer status --plan go-plus
tokenizer status --db "C:\ruta\a\opencode.db" --period-start 2026-11-01
```

Ejecutar los tests:

```powershell
pytest
```

## Configuración personal

Cada usuario configura sus propios datos. Se guardan fuera del repositorio, en `%APPDATA%\tokenizer\config.json`:

```powershell
tokenizer config --renews-at 2026-12-18T22:59Z --plan go
tokenizer config --db "C:\ruta\a\opencode.db"
tokenizer config
```

- `--renews-at`: próxima renovación de Go (UTC). Define el periodo mensual.
- `--plan`: `go`, `go-plus` o `go-teams`.
- `--db`: ruta a `opencode.db`, si no está en la ubicación por defecto.

## Secretos y privacidad

- No guardes claves, tokens ni datos personales en el repositorio. El `.gitignore` excluye `.env`, `*.key`, `secrets.*`, `config.local.*` y los archivos de uso `usage-*.json`, que contienen tu historial.
- Los precios se guardan en caché local en `%LOCALAPPDATA%\tokenizer\prices.json` durante 24 horas.

## Arquitectura en red

- Una máquina actúa como **servidor central** y muestra el panel web en el puerto `8765`.
- Regla de control: **el primer equipo que se inicia toma el control**. Los demás equipos envían su uso a ese servidor. Si el servidor se apaga, el siguiente equipo que se inicie toma el control.

## Hoja de ruta

1. Lector de `opencode.db` y cálculo de ventanas (**hecho**).
2. Exportación del uso de cada máquina y servidor central.
3. Panel web en red local (puerto por defecto `8765`).
4. Alertas configurables y aviso de calibración manual.
5. Calibración con el porcentaje real de la consola.
6. Recomendador de modelo según la tarea (segunda fase).

## Licencia

MIT. Consulta el archivo [LICENSE](LICENSE).
