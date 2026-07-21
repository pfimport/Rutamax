import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "comisiones.db"

DEFAULT_ESCALA = [
    {"desde": 0,           "hasta": 5_000_000,  "porcentaje": 5},
    {"desde": 5_000_000,  "hasta": 10_000_000, "porcentaje": 7},
    {"desde": 10_000_000, "hasta": 20_000_000, "porcentaje": 9},
    {"desde": 20_000_000, "hasta": None,        "porcentaje": 10},
]


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                email TEXT,
                telefono TEXT,
                xubio_id TEXT,
                escala_comision TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                fecha_alta TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clientes_vendedor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id_xubio TEXT NOT NULL UNIQUE,
                nombre_cliente TEXT NOT NULL,
                cuit TEXT,
                vendedor_id INTEGER REFERENCES vendedores(id),
                fecha_asignacion TEXT
            );

            CREATE TABLE IF NOT EXISTS facturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                xubio_id TEXT UNIQUE,
                numero TEXT,
                tipo TEXT,
                fecha_emision TEXT,
                fecha_cobro TEXT,
                cliente_id_xubio TEXT,
                cliente_nombre TEXT,
                vendedor_id INTEGER REFERENCES vendedores(id),
                neto REAL DEFAULT 0,
                iva REAL DEFAULT 0,
                total REAL DEFAULT 0,
                estado TEXT DEFAULT 'emitida',
                periodo_cobro_mes INTEGER,
                periodo_cobro_anio INTEGER,
                synced_at TEXT
            );

            CREATE TABLE IF NOT EXISTS resumenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendedor_id INTEGER NOT NULL REFERENCES vendedores(id),
                periodo_mes INTEGER NOT NULL,
                periodo_anio INTEGER NOT NULL,
                total_cobrado_neto REAL DEFAULT 0,
                comision_calculada REAL DEFAULT 0,
                porcentaje_aplicado REAL DEFAULT 0,
                escala_aplicada TEXT,
                cant_facturas INTEGER DEFAULT 0,
                detalle_facturas TEXT,
                notas TEXT,
                fecha_generacion TEXT NOT NULL,
                UNIQUE(vendedor_id, periodo_mes, periodo_anio)
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                facturas_nuevas INTEGER DEFAULT 0,
                facturas_actualizadas INTEGER DEFAULT 0,
                vendedores_nuevos INTEGER DEFAULT 0,
                clientes_nuevos INTEGER DEFAULT 0,
                estado TEXT,
                detalle TEXT
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS adelantos_comision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendedor_id INTEGER NOT NULL REFERENCES vendedores(id),
                periodo_mes INTEGER NOT NULL,
                periodo_anio INTEGER NOT NULL,
                fecha_corte TEXT NOT NULL,
                total_neto REAL NOT NULL,
                comision_pagada REAL NOT NULL,
                porcentaje_aplicado REAL NOT NULL,
                fecha_pago TEXT NOT NULL,
                notas TEXT,
                fecha_generacion TEXT NOT NULL,
                UNIQUE(vendedor_id, periodo_mes, periodo_anio, fecha_corte)
            );

            CREATE INDEX IF NOT EXISTS idx_facturas_periodo_vendedor
                ON facturas (vendedor_id, periodo_cobro_mes, periodo_cobro_anio, estado);

            CREATE INDEX IF NOT EXISTS idx_facturas_cliente
                ON facturas (cliente_id_xubio);

            CREATE INDEX IF NOT EXISTS idx_facturas_xubio_id
                ON facturas (xubio_id);
        """)
        # Migraciones para bases de datos existentes
        for sql in [
            "ALTER TABLE resumenes ADD COLUMN comision_pagada INTEGER DEFAULT 0",
            "ALTER TABLE resumenes ADD COLUMN fecha_pago_comision TEXT",
            "ALTER TABLE resumenes ADD COLUMN fecha_corte TEXT",
            "ALTER TABLE resumenes ADD COLUMN adelantos_pagados REAL DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass


def calcular_comision(total_neto: float, escala: list) -> tuple:
    """Progresivo: cada tramo aplica su % solo sobre la porción dentro de ese tramo."""
    escala_sorted = sorted(escala, key=lambda x: x["desde"])
    comision = 0.0
    ultimo_pct = 0.0
    for tramo in escala_sorted:
        desde = tramo["desde"]
        hasta = tramo["hasta"]
        pct = tramo["porcentaje"]
        if total_neto <= desde:
            break
        tope = min(total_neto, hasta) if hasta is not None else total_neto
        comision += (tope - desde) * pct / 100
        ultimo_pct = pct
        if hasta is None or total_neto <= hasta:
            break
    return round(comision, 2), ultimo_pct


def get_config(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_config(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]
