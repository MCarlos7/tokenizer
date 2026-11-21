# Tokenizer

Herramienta para ver cuánto te queda de tu suscripción **OpenCode Go**, en una o varias máquinas de tu red local, con CLI y panel web.

## Cómo funciona

OpenCode Go limita el uso con tres ventanas, todas expresadas como porcentaje de tu asignación mensual:

| Ventana | Límite                     | Reinicio                       |
| ------- | -------------------------- | ------------------------------ |
| 5 horas | 20 % (desde el primer uso) | 5 h después del primer uso     |
| Semanal | 50 %                       | Lunes 00:00 UTC                |
| Mensual | 100 %                      | Próxima renovación de tu plan  |

Cada modelo tiene un límite mensual en dólares (`go.monthly_usage` en el [catálogo de Go](https://opencode.ai/inference/go/v1/models)). Una petición consume `coste / límite del modelo` de tu asignación. Por ejemplo, $1.50 en un modelo con límite de $15 equivale al 10 %.

Tokenizer lee el historial local de OpenCode (`opencode.db`) en modo solo lectura. **Es una estimación**: no incluye el doble coste de algunas horas punta ni los precios de contexto largo. Puedes corregirla con `tokenizer calibrate`.

### Red: un host y varios clientes

- Cada equipo ejecuta Tokenizer. Se anuncian por UDP en la red local (puerto **8766**).
- Si no hay otro host activo, el equipo se convierte en **host**: sirve el panel y la API en el puerto **8765** y guarda el historial de todas las máquinas.
- Los demás equipos se conectan como **clientes** y envían su historial al host.
- Si el host se apaga, el siguiente equipo que detecte la ausencia toma el control y los clientes reenvían su historial.
- Si dos equipos se proclaman host a la vez, conserva el control el de nombre menor.
- Solo se envían **conteos de tokens, modelo, fecha y coste**. Nunca se envían prompts ni contenido de conversaciones.

## Requisitos

- Windows 10/11.
- Python 3.10 o superior.
- Todos los equipos de la red deben usar el **mismo token** y estar en la misma red local.

## Instalación

En cada equipo:

```powershell
git clone <URL-del-repositorio>
cd tokenizer
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Configura tu equipo (una sola vez):

```powershell
tokenizer config --token TU_TOKEN_COMPARTIDO --machine NOMBRE-DEL-EQUIPO --renews-at 2026-12-18T23:00Z --plan go
```

- `--token`: el mismo en todos los equipos. No lo subas al repositorio.
- `--machine`: nombre único de cada equipo. Por defecto usa el nombre de Windows.
- `--renews-at`: próxima renovación de Go (UTC). Define el periodo mensual.
- `--plan`: `go`, `go-plus` o `go-teams`.

La configuración se guarda en `%APPDATA%\tokenizer\config.json`, fuera del repositorio.

Windows pedirá permiso de firewall la primera vez. Acepta el acceso en redes privadas para los puertos 8765 y 8766.

## Uso

```powershell
tokenizer               # ejecuta en primer plano (igual que "tokenizer run")
tokenizer start         # ejecuta en segundo plano; registro en %LOCALAPPDATA%\tokenizer\daemon.log
tokenizer status        # consumo estimado de esta máquina
tokenizer calibrate --console-percent 12.5   # ejecútalo en el host
tokenizer config        # muestra la configuración (el token aparece oculto)
```

Panel web: abre `http://IP-DEL-HOST:8765` desde cualquier equipo de la red. La API está en `/api/status`.

### Arranque automático con OpenCode

El plugin `opencode-plugin/` ejecuta `tokenizer start` al cargar OpenCode. Para usarlo, agrega la ruta del plugin en tu `opencode.json` global:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["<ruta-a-tokenizer>/opencode-plugin"]
}
```

Requiere que el comando `tokenizer` esté disponible en el PATH (por ejemplo, con el entorno virtual activado o instalándolo con `pipx`). Si usas otra ruta, configúrala con `options.command`.

> El plugin aún no está probado contra el SDK real de OpenCode. Verifica que arranque al abrir OpenCode antes de depender de él.

### Alertas

Recibirás una notificación de Windows en el host cuando:

- Un límite (5 horas, semanal o mensual) supere el umbral configurado (por defecto 80 %). Cámbialo con `tokenizer config --alert-percent 85`.
- Hayan pasado más de 7 días desde la última calibración.

## Calibración

La estimación puede diferir de la consola. Para corregirla, anota el porcentaje mensual que muestra la consola y ejecútalo en el host:

```powershell
tokenizer calibrate --console-percent 12.5
```

## Desarrollo

```powershell
pytest
```

## Secretos y privacidad

- No guardes tokens, claves ni datos personales en el repositorio. El `.gitignore` excluye `.env`, `*.key`, `secrets.*`, `config.local.*` y los archivos de uso `usage-*.json`.
- Los precios se guardan en caché local en `%LOCALAPPDATA%\tokenizer\prices.json` durante 24 horas.
- El historial del host está en `%LOCALAPPDATA%\tokenizer\host.db`.

## Hoja de ruta

1. Lector de `opencode.db` y cálculo de ventanas (**hecho**).
2. Servidor central, descubrimiento en red y sincronización de historial (**hecho**).
3. Panel web y alertas (**hecho**).
4. Plugin de OpenCode para arranque automático (**pendiente de prueba**).
5. Recomendador de modelo según la tarea (segunda fase).

## Licencia

MIT. Consulta el archivo [LICENSE](LICENSE).
