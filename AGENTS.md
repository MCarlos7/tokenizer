# AGENTS.md

Tokenizer: monitor de cuotas de OpenCode Go para varias máquinas Windows en red local. Python 3.10+, solo biblioteca estándar (sin dependencias de runtime), layout `src/`, setuptools. Docs y mensajes de CLI en español; identificadores en inglés.

## Commands

- Setup: `python -m venv .venv` y luego `.venv\Scripts\python.exe -m pip install -e ".[dev]"`. En este equipo `python` es un alias de Microsoft Store: usa siempre la ruta del venv.
- Tests: `.venv\Scripts\python.exe -m pytest -q` (23 tests, sin red ni daemon). Un test: `-m pytest tests/test_usage.py::test_name`.
- Entrypoint: `tokenizer` o `python -m tokenizer` (`__main__.py`). Sin subcomando ejecuta `run` (daemon en primer plano).
- Subcomandos: `setup [--new|--join]`, `pair` (en el host), `run`, `start` (segundo plano, log en `%LOCALAPPDATA%\tokenizer\daemon.log`), `status` (consumo local), `config`, `calibrate --console-percent X` (en el host).
- Prueba de humo del daemon: no hay script en el repo. Construye un `Settings` con token temporal y llama `Daemon(settings).run()` en un hilo; no escribas el token real en scripts.
- No hay lint, formatter, typecheck ni CI configurados. No inventes comandos de esos.

## Architecture

- `cli.py`: parser y comandos. `_ensure_configured()` lanza el asistente de `setup` la primera vez si hay TTY.
- `daemon.py`: proceso por equipo. Envía latidos UDP por broadcast (`255.255.255.255:8766`) cada 5 s, escucha los de otros, elige host y sincroniza su historial. Cada 60 s en clientes, y en el host lee su `opencode.db` y comprueba alertas.
- `peers.py`: formato del latido (JSON con `app`, `v`, `machine`, `role`, `port`, `fp`, `pairing`), fingerprint de red (sha256 del token, 16 hex), tabla de pares con caducidad de 30 s, y `should_yield`: si dos hosts coexisten, cede el de nombre mayor.
- `server.py`: `TokenizerHTTPServer` en `0.0.0.0:8765`. Rutas: `POST /api/usage` (requiere cabecera `X-Tokenizer-Token`), `POST /api/pair` (código), `GET /api/status` (JSON), `GET /` y `/index.html` (panel con refresco de 30 s). Cuerpos máximos de 5 MB.
- `pairing.py`: código de 8 caracteres de `23456789ABCDEFGHJKMNPQRSTVWXYZ`, mostrado como `XXXX-XXXX`. Se guarda como sha256 con sal en `pairing.json`. Caduca a 10 min, se invalida al usarse y se bloquea tras 5 fallos. También `find_pairing_host` (escucha UDP) y `request_pairing` (HTTP).
- `host_store.py`: `host.db` (SQLite) con el historial de todas las máquinas. Clave `(machine, message_id)`, upsert idempotente.
- `opencode_db.py`: lee `opencode.db` en modo solo lectura (`file:...?mode=ro`). Usa mensajes `assistant` de `session_message` con `tokens` (`input`, `output`, `cache.read`, `cache.write`). `output` ya incluye el razonamiento, por lo que no se suma aparte.
- `pricing.py`: parsea `data[]` del catálogo de Go. Usa `go.monthly_usage[plan]` como límite en USD, `cost.text` como precio por millón. Caché en `%LOCALAPPDATA%\tokenizer\prices.json` durante 24 h. Si falla la red y hay caché, usa la caché.
- `usage.py`: cálculo de ventanas (ver Domain). `record_percent` = `coste / límite_del_modelo * 100 * factor`.
- `alerts.py` y `notify.py`: mensajes estables (sin porcentaje exacto, para no repetir avisos) y notificación de escritorio con PowerShell en Windows.
- `opencode-plugin/`: plugin TypeScript que llama a `tokenizer start` al cargarse. Sin lockfile ni build y sin probar contra `@opencode/plugin`.

## Domain (verificado en el catálogo y en docs de Go)

- Todos los modelos de pago comparten una sola asignación mensual. Por modelo, `go.monthly_usage` es cuánto cubriría el plan si solo usaras ese modelo. Gastar `$1.50` en un modelo con límite `$15` consume el 10 % de la asignación.
- Ventanas: 5 h (20 %) desde el primer uso, semanal (50 %) que reinicia lunes 00:00 UTC, mensual (100 %) desde la renovación (`renews_at`). Sin `renews_at`, usa meses naturales en UTC.
- Modelos con `monthly_usage` `null` (gratuitos o sin límite publicado) no suman consumo.
- Solo cuentan los registros de proveedor `opencode-go`.
- `tokenizer status` muestra porcentajes por modelo; no existen límites individuales separados.
- Los precios de horas punta (multiplicadores) y de contexto largo no se modelan; `calibrate` corrige la estimación con el porcentaje de la consola.

## Config, state and paths

- Configuración de usuario: `%APPDATA%\tokenizer\config.json`. Contiene `token`, `machine`, `plan`, `renews_at`, `db`, `alert_percent`, `calibration_factor`, `calibrated_at`. Carga con `load_settings()`.
- Estado en `%LOCALAPPDATA%\tokenizer\`: `prices.json`, `host.db`, `pairing.json`, `daemon.log`.
- Los equipos cliente reciben token, plan y `renews_at` durante el emparejamiento.
- Las alertas y la calibración solo ocurren en el host. Un cliente nunca escribe `host.db`.
- Intervalos de referencia: latido 5 s, caducidad de par 30 s, arranque 6 s de escucha, sincronización 60 s, alerta por defecto 80 %, aviso de calibración tras 7 días.

## Gotchas

- Los puertos 8765 (HTTP) y 8766 (UDP) son fijos. Un `tokenizer run` o `start` activo hace fallar los tests de red y las pruebas de humo. El daemon bloquea 8766 para impedir instancias duplicadas. No hay `stop`: termina el proceso `python -m tokenizer run` desde el Administrador de tareas o con `Stop-Process`.
- El catálogo de Go responde 403 al User-Agent por defecto de Python. Mantén `USER_AGENT` en `config.py`.
- Los tests que tocan emparejamiento redirigen `LOCALAPPDATA` con `monkeypatch`. Haz lo mismo en tests nuevos. Nunca escribas el token en logs, tests ni archivos del repo.
- `cli.main` fuerza stdout en UTF-8 para que la salida en español no se rompa en la consola de Windows.
- `cmd_setup` usa `_ask`, que cae en el valor por defecto si no hay entrada (`EOFError`). Así funciona sin consola; no quites esa protección.
- Los avisos de CRLF de Git en Windows son normales; no reescribas finales de línea.

## Repository rules

- El repo es público. No añadas nombres de usuario, correos, rutas personales ni tokens a archivos versionados. La licencia (`LICENSE`) lleva `MCarlos7` por petición del dueño; no la cambies.
- Commits con la identidad local del repo (`Tokenizer Contributors <tokenizer@users.noreply.github.com>`). No uses la identidad global.
- Remoto `origin` es GitHub (`MCarlos7/tokenizer`), rama `main`. Trabaja sobre `main` salvo que el usuario pida otra cosa.
