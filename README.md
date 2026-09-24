# Claude Usage Tray

Pequeña aplicación para la bandeja del sistema de Windows que muestra el consumo de tu plan de Claude (claude.ai): porcentaje usado y restante de la sesión actual (ventana de 5 h) y del límite semanal, con el tiempo que falta para cada reinicio.

- El icono muestra el % usado de la sesión y cambia de color: verde (< 50 %), ámbar (< 80 %) y rojo (≥ 80 %).
- Clic derecho: detalle de sesión y límites semanales, actualizar, abrir la página de uso y editar la configuración.
- Se actualiza cada 60 s y avisa con una notificación al llegar al 80 % y al 95 % de la sesión.

> **Aviso:** usa el endpoint interno que alimenta *Ajustes > Uso* en claude.ai. No es una API pública ni documentada, así que puede dejar de funcionar sin previo aviso. Proyecto no oficial, sin relación con Anthropic.

## Requisitos

- Windows 10/11
- Python 3.10 o superior

## Instalación

```bash
git clone https://github.com/Arzu260/claude-usage-tray.git
cd claude-usage-tray
pip install -r requirements.txt
pythonw claude_usage_tray.py
```

## Configuración

En la primera ejecución se crea `%APPDATA%\ClaudeUsageTray\config.json`:

```json
{
  "session_key": "",
  "org_id": ""
}
```

1. Abre claude.ai con tu sesión iniciada y pulsa F12.
2. Firefox: pestaña **Almacenamiento → Cookies → https://claude.ai**. Chrome/Edge: **Aplicación → Cookies → https://claude.ai**.
3. Copia el valor de la cookie `sessionKey` y pégalo en `session_key`.
4. Clic derecho en el icono → **Actualizar ahora**.

`org_id` se rellena automáticamente. También puedes pasar la clave con la variable de entorno `CLAUDE_SESSION_KEY`.

> 🔒 La `sessionKey` da acceso completo a tu cuenta. Trátala como una contraseña: no la compartas ni la subas a ningún repositorio. Cuando caduque, el icono mostrará un **?** gris y habrá que copiarla de nuevo.

## Arranque con Windows

Crea un acceso directo a `pythonw.exe claude_usage_tray.py` en la carpeta que abre `Win + R → shell:startup`.

## Generar un .exe

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole claude_usage_tray.py
```

El ejecutable queda en `dist/`.

## Personalización

Al principio del script puedes ajustar `REFRESH_SECONDS` (intervalo de actualización) y `ALERT_THRESHOLDS` (umbrales de aviso).
