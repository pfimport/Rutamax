"""Inventario de sistemas en esta PC. SOLO LEE: no modifica, mueve ni borra nada.

Busca carpetas que parezcan un sistema (app.py / INICIAR.bat / bases .db) y arma un
informe para decidir cuál es el correcto y cuáles sobran.
Uso: python escanear_sistemas.py [carpeta_raiz ...]   (sin argumentos: escritorio, documentos,
descargas, OneDrive y las demás unidades, por ejemplo G: de Google Drive)
"""
import os
import sqlite3
import string
import sys
import time
from datetime import datetime

SALTAR = {
    "windows", "program files", "program files (x86)", "programdata", "appdata",
    "$recycle.bin", "system volume information", "node_modules", ".git", "venv",
    ".venv", "site-packages", "__pycache__", "$windows.~bt", "recovery",
}
LIMITE_SEGUNDOS = 600


def fecha(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def leer_texto(ruta, limite=400_000):
    try:
        with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limite)
    except Exception:
        return ""


def tamano_carpeta(ruta, tope=300):
    """Suma el tamaño de los archivos de la carpeta (sin entrar a subcarpetas pesadas)."""
    total, n = 0, 0
    try:
        for nombre in os.listdir(ruta):
            p = os.path.join(ruta, nombre)
            if os.path.isfile(p):
                total += os.path.getsize(p)
                n += 1
                if n >= tope:
                    break
    except Exception:
        pass
    return total


def info_base(ruta_db):
    """Cuenta registros de comisiones.db abriéndola en modo solo lectura."""
    datos = {"archivo": fecha(os.path.getmtime(ruta_db)),
             "kb": round(os.path.getsize(ruta_db) / 1024)}
    try:
        con = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True, timeout=5)
        cur = con.cursor()

        def uno(sql):
            try:
                return cur.execute(sql).fetchone()[0]
            except Exception:
                return None

        datos["facturas"] = uno("SELECT COUNT(*) FROM facturas")
        datos["ultima_factura"] = uno("SELECT MAX(fecha_emision) FROM facturas")
        datos["ultimo_cobro"] = uno("SELECT MAX(fecha_cobro) FROM facturas")
        datos["vendedores"] = uno("SELECT COUNT(*) FROM vendedores")
        datos["resumenes"] = uno("SELECT COUNT(*) FROM resumenes")
        datos["pagos_registrados"] = uno("SELECT COUNT(*) FROM pagos_comision")
        datos["ultima_sync"] = uno("SELECT MAX(fecha) FROM sync_log")
        con.close()
    except Exception as e:
        datos["error"] = str(e)[:120]
    return datos


def analizar(ruta, archivos):
    minus = {a.lower(): a for a in archivos}
    app_py = os.path.join(ruta, minus["app.py"]) if "app.py" in minus else None
    texto_app = leer_texto(app_py) if app_py else ""
    es_comisiones = "Sistema de Comisiones PF" in texto_app or "comisiones.db" in minus
    bats = sorted(a for a in archivos if a.lower().endswith((".bat", ".vbs")))
    r = {
        "ruta": ruta,
        "es_comisiones": es_comisiones,
        "app_py": fecha(os.path.getmtime(app_py)) if app_py else None,
        "bats": bats,
        "dbs": sorted(a for a in archivos if a.lower().endswith(".db")),
        "tiene_actualizar": "actualizar.bat" in minus,
        "version_reciente": "fecha_cobro_manual" in texto_app,
        "tiene_backups": os.path.isdir(os.path.join(ruta, "backups")),
        "kb_archivos": round(tamano_carpeta(ruta) / 1024),
    }
    if r["tiene_backups"]:
        try:
            r["cant_backups"] = len([x for x in os.listdir(os.path.join(ruta, "backups")) if x.endswith(".db")])
        except Exception:
            r["cant_backups"] = None
    if "comisiones.db" in minus:
        r["base"] = info_base(os.path.join(ruta, minus["comisiones.db"]))
    return r


def es_candidata(archivos):
    m = {a.lower() for a in archivos}
    tiene_py = "app.py" in m or "main.py" in m
    tiene_bat = any(a.endswith((".bat", ".vbs")) for a in m)
    tiene_db = any(a.endswith(".db") for a in m)
    return (tiene_py and (tiene_bat or tiene_db)) or "comisiones.db" in m or "iniciar.bat" in m


def raices_por_defecto():
    raices = []
    home = os.path.expanduser("~")
    for sub in ("Desktop", "Escritorio", "Documents", "Documentos", "Downloads", "Descargas",
                "OneDrive", "Google Drive", "Mi unidad"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            raices.append(p)
    if os.name == "nt":
        for letra in string.ascii_uppercase:
            unidad = f"{letra}:\\"
            if letra != "C" and os.path.exists(unidad):
                raices.append(unidad)
    return raices


def main():
    raices = sys.argv[1:] or raices_por_defecto()
    print("Buscando sistemas (solo lectura). Esto puede tardar unos minutos...")
    print("Carpetas a revisar:", *raices, sep="\n  ")
    inicio = time.time()
    encontrados, zips, vistos = [], [], set()
    for raiz in raices:
        for carpeta, subdirs, archivos in os.walk(raiz):
            if time.time() - inicio > LIMITE_SEGUNDOS:
                print("Se alcanzó el límite de tiempo; el informe puede estar incompleto.")
                break
            subdirs[:] = [d for d in subdirs if d.lower() not in SALTAR]
            real = os.path.realpath(carpeta)
            if real in vistos:
                subdirs[:] = []
                continue
            vistos.add(real)
            for a in archivos:
                if a.lower().endswith(".zip") and ("rutamax" in a.lower() or "comisiones" in a.lower()):
                    zips.append(os.path.join(carpeta, a))
            if es_candidata(archivos):
                try:
                    encontrados.append(analizar(carpeta, archivos))
                except Exception as e:
                    encontrados.append({"ruta": carpeta, "error": str(e)[:120]})

    lineas = [f"INVENTARIO DE SISTEMAS — {fecha(time.time())}",
              "(Solo lectura: este informe no modificó ni borró nada)", ""]
    comis = [x for x in encontrados if x.get("es_comisiones")]
    otros = [x for x in encontrados if not x.get("es_comisiones")]

    lineas.append(f"=== COPIAS DEL SISTEMA DE COMISIONES PF: {len(comis)} ===")
    for i, x in enumerate(comis, 1):
        lineas += [f"\n[{i}] {x['ruta']}"]
        if "error" in x:
            lineas.append(f"    No se pudo leer: {x['error']}")
            continue
        lineas.append(f"    app.py modificado: {x['app_py']} | versión reciente (fecha editable): "
                      f"{'SI' if x['version_reciente'] else 'no'} | tiene ACTUALIZAR.bat: "
                      f"{'SI' if x['tiene_actualizar'] else 'no'}")
        b = x.get("base")
        if b:
            lineas.append(f"    BASE comisiones.db: modificada {b['archivo']}, {b['kb']} KB")
            if "error" in b:
                lineas.append(f"      no se pudo abrir: {b['error']}")
            else:
                lineas.append(f"      facturas: {b['facturas']} (última emitida {b['ultima_factura']}, "
                              f"último cobro {b['ultimo_cobro']}) | vendedores: {b['vendedores']} | "
                              f"resúmenes: {b['resumenes']} | pagos cargados: {b['pagos_registrados']} | "
                              f"última sync: {b['ultima_sync']}")
        else:
            lineas.append("    SIN comisiones.db (probablemente una copia de programa sin datos)")
        if x.get("tiene_backups"):
            lineas.append(f"    carpeta backups: {x.get('cant_backups')} copias de la base")
        if x["dbs"] and x["dbs"] != ["comisiones.db"]:
            lineas.append(f"    otras bases en la carpeta: {', '.join(x['dbs'])}")

    lineas.append(f"\n=== OTROS SISTEMAS / CARPETAS PARECIDAS (no son Comisiones PF): {len(otros)} ===")
    for x in otros:
        extra = f" | bats: {', '.join(x['bats'][:6])}" if x.get("bats") else ""
        bases = f" | bases: {', '.join(x['dbs'][:4])}" if x.get("dbs") else ""
        lineas.append(f"  - {x['ruta']}  (app.py: {x.get('app_py')}){extra}{bases}")

    lineas.append(f"\n=== ZIPs descargados del sistema: {len(zips)} ===")
    for z in zips:
        lineas.append(f"  - {z}  ({fecha(os.path.getmtime(z))})")

    destino = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(destino):
        destino = os.path.join(os.path.expanduser("~"), "Escritorio")
    if not os.path.isdir(destino):
        destino = os.getcwd()
    ruta_informe = os.path.join(destino, "inventario_sistemas.txt")
    with open(ruta_informe, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))
    print(f"\nInforme guardado en: {ruta_informe}")


if __name__ == "__main__":
    main()
