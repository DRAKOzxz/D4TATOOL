# D4TATOOL

Gestor local de proyectos de GitHub. Descarga un repositorio, analiza su
contenido, deduce cómo se ejecuta, prepara su entorno y lo deja listo para lanzar desde
un menú de terminal. Sin dependencias externas y sin configuración manual.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-windows-lightgrey)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

---

## Qué es

D4TATOOL es una utilidad de escritorio pensada para quien acumula repositorios de
GitHub y acaba con una carpeta llena de proyectos que no recuerda cómo arrancar.
Centraliza el ciclo completo en un solo sitio:

- Importa el repositorio por URL.
- Detecta el lenguaje y los puntos de entrada.
- Instala dependencias en un entorno aislado por proyecto.
- Guarda la orden de ejecución en un archivo de configuración propio.
- Lanza el proyecto y ofrece un menú de recuperación si falla.

El objetivo es reducir a un par de pulsaciones algo que normalmente exige leer el
README de cada repositorio, crear el entorno virtual a mano y recordar el comando
exacto. Todos los proyectos viven bajo `projets/`, con su propia configuración y su
propio entorno, de forma que nada se mezcla entre ellos.

## Qué no es

- No es un gestor de paquetes ni un orquestador de contenedores.
- No compila código: solo invoca el compilador o el intérprete que ya corresponda.
- No aísla la ejecución. El código del proyecto corre con los permisos de tu usuario,
  igual que si lo lanzaras desde una consola. Trata los repos como código de terceros.
- No adivina de forma infalible. Cuando la detección es ambigua lo indica con un
  porcentaje de confianza y ofrece alternativas.

---

## Requisitos

- Windows 10 u 11 (la interfaz usa la consola de Windows; en Linux funciona con
  limitaciones).
- Python 3.8 o superior.
- Terminal de al menos 100x34 caracteres.
- Opcional pero recomendado: `git` para clonar en vez de descargar el ZIP.
- Opcional: `winget` para que la herramienta pueda instalar por sí sola los runtimes
  que falten.

No hay dependencias de terceros: todo usa la biblioteca estándar.

## Instalación

```bat
git clone https://github.com/<usuario>/d4tatool.git
cd d4tatool
python d4tatool.py
