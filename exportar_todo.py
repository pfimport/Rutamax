"""Exporta toda la base de datos a archivos CSV legibles en Excel."""
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "comisiones.db"
EXPORT_DIR = Path(__file__).parent / "exportaciones"

def exportar():
    if not DB_PATH.exists():
        print("No se encontro comisiones.db")
        return

    EXPORT_DIR.mkdir(exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    carpeta = EXPORT_DIR / fecha
    carpeta.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    tablas = {
        "facturas": {
            "query": """
                SELECT f.numero, f.tipo, f.fecha_emision, f.fecha_cobro,
                       f.cliente_nombre, f.neto, f.iva, f.total,
                       f.estado, f.periodo_cobro_mes, f.periodo_cobro_anio,
                       v.nombre as vendedor
                FROM facturas f
                LEFT JOIN vendedores v ON f.vendedor_id = v.id
                ORDER BY f.fecha_emision DESC
            """,
            "cols": ["Numero","Tipo","Fecha Emision","Fecha Cobro","Cliente",
                     "Neto","IVA","Total","Estado","Mes","Anio","Vendedor"],
        },
        "vendedores": {
            "query": "SELECT nombre, email, telefono, activo, fecha_alta FROM vendedores ORDER BY nombre",
            "cols": ["Nombre","Email","Telefono","Activo","Fecha Alta"],
        },
        "resumenes": {
            "query": """
                SELECT v.nombre as vendedor,
                       r.periodo_mes, r.periodo_anio,
                       r.total_cobrado_neto, r.porcentaje_aplicado,
                       r.comision_calculada, r.cant_facturas,
                       r.comision_pagada, r.fecha_pago_comision,
                       r.fecha_corte, r.notas, r.fecha_generacion
                FROM resumenes r
                JOIN vendedores v ON r.vendedor_id = v.id
                ORDER BY r.periodo_anio DESC, r.periodo_mes DESC, v.nombre
            """,
            "cols": ["Vendedor","Mes","Anio","Total Cobrado Neto","% Tramo",
                     "Comision","Facturas","Comision Pagada","Fecha Pago",
                     "Fecha Corte","Notas","Generado"],
        },
    }

    archivos = []
    for nombre, cfg in tablas.items():
        rows = conn.execute(cfg["query"]).fetchall()
        archivo = carpeta / f"{nombre}_{fecha}.csv"
        with open(archivo, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cfg["cols"])
            w.writerows([list(r) for r in rows])
        archivos.append((nombre, len(rows), archivo))
        print(f"  {nombre}: {len(rows)} filas → {archivo.name}")

    conn.close()
    print(f"\nExportacion completa en: {carpeta}")
    return carpeta

if __name__ == "__main__":
    print("Exportando datos a CSV...\n")
    exportar()
    input("\nPresiona Enter para cerrar...")
