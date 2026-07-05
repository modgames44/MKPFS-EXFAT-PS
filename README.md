<!-- markdownlint-disable MD033 -->
<p align="center">
  <img src="docs/images/logo.png" alt="MKPSF Logo" width="120">
</p>

<h1 align="center">🎮 MKPSF & exFAT Builder All-in-One</h1>

<p align="center">
  <strong>La herramienta definitiva para Windows para la gestión de imágenes de juegos PS5 y despliegue de payloads</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Plataforma-Windows%2010%20%2F%2011-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square" alt="Python">
  <img src="https://img.shields.io/github/license/ModGames44/mkpfs-gui?style=flat-square" alt="License">
  <img src="https://img.shields.io/github/v/release/ModGames44/mkpfs-gui?style=flat-square" alt="Release">
  <img src="https://img.shields.io/github/downloads/ModGames44/mkpfs-gui/total?style=flat-square" alt="Downloads">
  <img src="https://img.shields.io/badge/estado-estable-brightgreen?style=flat-square" alt="Status">
</p>

---

## 📖 Descripción general

**MKPSF & exFAT Builder All-in-One** es una aplicación unificada para Windows que integra **MkPFS**, **Generador de imágenes exFAT**, **generación de índices AMPR** y **Payload Sender** en una única interfaz moderna.

Ya no necesitas cambiar entre múltiples herramientas — todo lo que necesitas para la gestión de imágenes de juegos PS5 está disponible en un solo lugar.

Diseñada para ser **rápida, fiable y fácil de usar**.

> ⚠️ **Herramienta para Homebrew y copias de seguridad personales**
>
> Este software está pensado exclusivamente para juegos y contenido que **poseas legalmente y hayas volcado tú mismo**.
>
> **No** descarga juegos, descifra paquetes comerciales, elude DRM ni proporciona contenido con derechos de autor.

---

## ✨ Características

### 📦 Generador de imágenes
- ✅ Creación de imágenes exFAT (`.exfat`)
- ✅ Creación de imágenes PFS comprimidas (`.ffpfsc`)
- ✅ Creación de imágenes PFS sin comprimir (`.ffpfs`)
- ✅ Verificación automática de imágenes
- ✅ Barra de progreso en tiempo real con velocidad y ETA

### 📄 Generador de índices AMPR
- ✅ **Generación automática** durante la conversión (para soporte de emulación)
- ✅ **Generación manual** con botón dedicado (funciona incluso sin `fakelib/libSceAmpr.sprx`)
- ✅ Perfecto para usuarios que mantienen juegos en formato carpeta sin reempaquetar

### 🚀 Payload Sender
- ✅ Envío de payloads `.js`, `.elf`, `.bin`, `.jar` directamente a PS5
- ✅ Botones rápidos: Kernel, KStuff, ShadowMount, ELFLoader, FTP
- ✅ Selección de payload personalizado
- ✅ Salida en vivo de la consola

### 🎯 Funcionalidades adicionales
- ✅ Vista previa del icono del juego (`sce_sys/icon0.png`) al cargar una carpeta
- ✅ Interfaz limpia y moderna con PyQt6
- ✅ Sin dependencias externas (OSFMount, etc.)
- ✅ Ejecutable único para facilitar la distribución

---

## 🖥️ Capturas de pantalla

> *Añade aquí las capturas de la ventana principal, la pestaña de conversión y el enviador de payloads.*

<img width="1254" height="848" alt="Captura de pantalla 2026-07-05 181013" src="https://github.com/user-attachments/assets/882dd1c7-5e02-4539-8939-6135ffcb6e39" />

---

## ⚡ Guía rápida

1. **Descarga** la última versión desde la sección [Releases](https://github.com/ModGames44/mkpfs-gui/releases).
2. **Ejecuta** `MkPFS.exe` (como Administrador para todas las funciones).
3. **Abre** la pestaña **Conversión**.
4. **Carga** tu volcado de juego PS5 (carpeta o archivo).
5. **Selecciona** el formato de salida:
   - `ffpfsc` – Comprimido (recomendado)
   - `ffpfs` – Sin comprimir
   - `exfat` – Imagen exFAT estándar
6. **Opcional:** Activa "Generar índice automáticamente al convertir" para soporte de emulación AMPR.
7. **Haz clic** en "CONVERTIR" y observa el progreso en tiempo real.
8. **Cambia** a la pestaña **Payload Sender** para enviar payloads directamente a tu PS5.

---

## 📂 Formatos soportados

| Formato | Descripción |
|---------|-------------|
| **exFAT** | Imagen exFAT montable estándar |
| **FFPFSC** | Imagen PFS comprimida (recomendada para emulación) |
| **FFPFS** | Imagen PFS sin comprimir |

---

## ⭐ ¿Por qué MKPSF & exFAT Builder All-in-One?

- ✅ **Interfaz moderna para Windows** – Limpia, intuitiva y fácil de navegar.
- ✅ **Múltiples formatos de imagen** – exFAT, FFPFSC y FFPFS en una sola herramienta.
- ✅ **Generación de índices AMPR integrada** – Modos automático y manual.
- ✅ **Payload Sender incluido** – No necesitas herramientas separadas.
- ✅ **Progreso en tiempo real** – Velocidad, ETA y seguimiento de fases.
- ✅ **Vista previa del icono del juego** – Confirmación visual al cargar carpetas.
- ✅ **Desarrollo activo** – Actualizaciones y mejoras regulares.

---

## 🙏 Créditos y agradecimientos

Gracias a toda la comunidad de Homebrew de PS5, especialmente a:

| Proyecto | Autor | Enlace |
|----------|-------|--------|
| **MkPFS** | PSBrew | [GitHub](https://github.com/PSBrew/MkPFS) |
| **PS5 exFAT Builder** | kerrdec97 | [GitHub](https://github.com/kerrdec97/ps5-exfat-builder) |
| **Colaboración y mejoras** | **Darkmors** | [GitHub](https://github.com/Darkmors) |

> ❤️ **Agradecimiento especial** a **Darkmors** por su valiosa ayuda en la integración, corrección de errores, implementación del generador de índices AMPR y mejoras generales de la aplicación.

Consulta **THIRD_PARTY_NOTICES.md** para obtener información completa sobre licencias.

---

## ⚠️ Aviso legal

Este software está pensado **exclusivamente para contenido que poseas legalmente**.

**No está afiliado ni respaldado por Sony Interactive Entertainment.**

Úsalo bajo tu propia responsabilidad.

---

## ⭐ Apoya el proyecto

Si disfrutas usando **MKPSF & exFAT Builder All-in-One**:

- ⭐ **Dale una estrella** al repositorio
- 🐛 **Reporta errores** mediante Issues
- 💡 **Comparte ideas** para futuras funciones

---

## 📄 Licencia

Este proyecto integra herramientas de terceros; consulta sus respectivas licencias.

La interfaz y el código de integración se distribuyen bajo la **Licencia MIT**.

---

<p align="center">
  <sub>Hecho con ❤️ para la comunidad Homebrew de PS5</sub>
</p>
