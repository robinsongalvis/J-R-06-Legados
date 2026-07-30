#!/usr/bin/env python3
"""Protege el sistema de diseño: impide que entren valores nuevos fuera del sistema.

No es documentación, es política. La definición de terminado de la fase 1 del
roadmap, hecha ejecutable: en vez de preguntarse "¿algún componente se salió del
sistema?", se cuenta.

MODO TRINQUETE (el que se usa en CI)
    El memorial arranca con ~89 valores fuera del sistema. Si el guardián
    bloqueara todo lo que esté por encima de la meta, ningún merge pasaría nunca
    y el guardián se desactivaría a la semana. Así que compara contra una LÍNEA
    BASE guardada, y solo falla si la deriva AUMENTA.

    El número solo puede bajar. Cada fase del roadmap lo baja un poco, y la
    línea base se actualiza con --guardar-base cuando eso pasa.

Uso:
    python3 scripts/design_guard.py                 # compara contra la base
    python3 scripts/design_guard.py --guardar-base  # fija la base actual
    python3 scripts/design_guard.py --meta          # ignora la base, exige la meta

Salida: 0 si no hay deriva nueva, 1 si algo empeoró.
"""
import json
import re
import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "templates" / "perfil.html"
BASE = pathlib.Path(__file__).resolve().parent / "design_guard_base.json"

# ── El sistema acordado (roadmap, fase 1) ─────────────────────────────
METAS = {
    "tamaños de letra": 7,
    "espaciados": 7,
    "radios": 4,
    "sombras": 4,
    "duraciones": 3,
    "curvas": 2,
}

# Excepciones firmadas. Están escritas porque una excepción que hay que
# escribir es una excepción que alguien decidió, no una que se coló.
EXCEPCIONES = {
    "tamaños de letra": {40.0, 72.0, 56.0},  # nombre en la intro · comillas · paloma
    "espaciados": {20.0},                     # canaleta lateral: medida de página
    "radios": {"50%"},                        # círculos: retrato, avatares
    "duraciones": set(),                      # ahora las cubre RAMPA_ATMOSFERA
    "curvas": {"linear", "ease-in-out"},      # ver RAMPA_ATMOSFERA
}
RAMPA_ICONOS = {16.0, 20.0, 28.0, 44.0}       # vive aparte de la escala de texto

# La atmósfera no es interfaz. Una llama de vela que late a 2s y un botón que
# responde en 0.3s no pertenecen a la misma escala, y meterlos en la misma cuenta
# empujaría a acelerar la llama para bajar un número. Estos valores están fuera
# de la escala de respuesta, pero NO fuera de control: agregar uno nuevo exige
# escribirlo acá, o sea decidirlo.
#
# Su curva es 'ease-in-out', simétrica a propósito: son respiraciones y bucles
# 'alternate', y una curva asimétrica les daría un latido cojo.
RAMPA_ATMOSFERA = {
    0.85, 1.05,   # ondaLatido: el desfase del waveform, un ritmo y no una escala
    0.9,          # latidoCorazon del doble toque (el JS lo espera a los 950ms)
    1.2,          # crossfade de la portada
    2.0,          # flicker de las velas
    3.0,          # floatUp: íconos que respiran
    5.0,          # deriva de las partículas de luz
    6.0,          # zoom lento del hero
    # La coreografía del intro: una sola composición, no cuatro decisiones sueltas
    1.0, 1.5, 1.8, 2.2,
}


def css_principal(ruta: pathlib.Path) -> str:
    """El <style> más largo: saltea el <noscript><style> anti-página-en-blanco."""
    bloques = re.findall(r"<style>(.*?)</style>", ruta.read_text(encoding="utf-8"), re.S)
    return max(bloques, key=len) if bloques else ""


def duraciones(css: str) -> set:
    """Los tiempos del sistema, más cualquier literal que se haya colado.

    Contar solo literales dejaría al guardián ciego apenas las reglas usan
    var(--mov-…): vería cero y cantaría victoria. Así que mide las DOS cosas —
    los tokens declarados y los números sueltos que sigan dentro de un
    transition/animation— y las suma. Un valor nuevo no puede esconderse ni
    escribiéndolo a mano ni inventando un token.
    """
    tokens = {float(v) for v in re.findall(r"--mov-[\w-]+\s*:\s*(\d+(?:\.\d+)?)s", css)}
    literales = set()
    for m in re.finditer(r"(?:transition|animation)\s*:\s*([^;{}]+)", css):
        literales.update(float(n) for n in re.findall(r"(?<![\w-])(\d+(?:\.\d+)?)s\b", m.group(1)))
    return (tokens | literales) - RAMPA_ATMOSFERA


def medir(css: str) -> dict:
    def px(prop):
        vals = set()
        for m in re.finditer(prop + r"\s*:\s*([^;}]+)[;}]", css):
            vals.update(float(n) for n in re.findall(r"(\d+(?:\.\d+)?)px", m.group(1)))
        return vals

    return {
        "tamaños de letra": px(r"font-size") - EXCEPCIONES["tamaños de letra"] - RAMPA_ICONOS,
        "espaciados": px(r"(?:padding|margin)(?:-\w+)?") - EXCEPCIONES["espaciados"],
        # Un radio en cero no es una elección de radio, es la ausencia de una
        # (el contenedor a sangre en móvil). Mismo criterio que el 'none' de las
        # sombras: no cuenta como valor del sistema.
        "radios": {v.strip() for v in re.findall(r"border-radius\s*:\s*([^;}]+)[;}]", css)
                   if not re.match(r"^0(\s|;|$|\s*!important)", v.strip())}
                  - EXCEPCIONES["radios"],
        "sombras": {v.strip() for v in re.findall(r"box-shadow\s*:\s*([^;}]+)[;}]", css)
                    if "none" not in v},
        "duraciones": duraciones(css),
        "curvas": set(re.findall(
            r"(cubic-bezier\([^)]*\)|ease-in-out|ease-out|ease-in|linear|\bease\b)", css))
                  - EXCEPCIONES["curvas"],
    }


def main() -> int:
    if not PLANTILLA.exists():
        print(f"No encuentro {PLANTILLA}")
        return 2

    conteos = {k: len(v) for k, v in medir(css_principal(PLANTILLA)).items()}

    if "--guardar-base" in sys.argv:
        BASE.write_text(json.dumps(conteos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  Línea base guardada en {BASE.name}:")
        for k, v in conteos.items():
            print(f"    {k:20} {v}")
        return 0

    exigir_meta = "--meta" in sys.argv
    base = METAS if exigir_meta else (
        json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else METAS)
    etiqueta = "meta" if exigir_meta else "base"

    print(f"  {'sistema':20} {'hoy':>5} {etiqueta:>6} {'meta':>6}   estado")
    print("  " + "─" * 54)

    empeoro = []
    for nombre, meta in METAS.items():
        hoy = conteos[nombre]
        tope = base.get(nombre, meta)
        if hoy > tope:
            estado = f"+{hoy - tope} NUEVO"
            empeoro.append((nombre, hoy - tope))
        elif hoy < tope:
            estado = f"−{tope - hoy} mejor"
        else:
            estado = "igual" if hoy > meta else "en meta"
        print(f"  {nombre:20} {hoy:5} {tope:6} {meta:6}   {estado}")

    total_hoy = sum(conteos.values())
    total_meta = sum(METAS.values())
    print(f"\n  Deriva total: {total_hoy} valores · meta {total_meta}")

    if empeoro:
        print("\n  BLOQUEADO. Entraron valores nuevos fuera del sistema:")
        for nombre, cuantos in empeoro:
            print(f"    {nombre}: +{cuantos}")
        print("\n  Si el valor nuevo es deliberado, declaralo en EXCEPCIONES.")
        print("  Si bajaste la deriva en otra parte, corré --guardar-base.")
        return 1

    if total_hoy <= total_meta:
        print("\n  Todo dentro del sistema. La fase 1 está terminada.")
    else:
        print("\n  Sin deriva nueva. El número solo puede bajar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
