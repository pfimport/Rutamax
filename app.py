import csv
import io
import json
import asyncio
import threading
from datetime import datetime, date
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import (
    init_db, get_conn, row_to_dict, rows_to_list,
    calcular_comision, DEFAULT_ESCALA, get_config, set_config,
)
from xubio import XubioClient


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_nota_credito(tipo: str) -> bool:
    if not tipo:
        return False
    t = tipo.lower()
    return "nota de cr" in t or t.startswith("nc ") or t == "nc" or "/nc" in t or "n.c." in t


def get_xubio() -> XubioClient:
    client_id = get_config("xubio_client_id")
    client_secret = get_config("xubio_client_secret")
    if not client_id or not client_secret:
        raise HTTPException(400, "Credenciales de Xubio no configuradas")
    return XubioClient(client_id, client_secret)


def _mes_nombre(mes: int) -> str:
    nombres = ["", "Enero","Febrero","Marzo","Abril","Mayo","Junio",
               "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    return nombres[mes] if 1 <= mes <= 12 else str(mes)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Sincronizar automáticamente al iniciar si Xubio está configurado
    client_id = get_config("xubio_client_id")
    client_secret = get_config("xubio_client_secret")
    if client_id and client_secret:
        def _auto_sync():
            global _sync_running, _last_sync_result
            _sync_running = True
            try:
                _last_sync_result = _do_sync(XubioClient(client_id, client_secret), 1)
            except Exception as e:
                _last_sync_result = {"error": str(e)}
            finally:
                _sync_running = False
        threading.Thread(target=_auto_sync, daemon=True).start()
    yield


app = FastAPI(title="Sistema de Comisiones PF", lifespan=lifespan)


# ── Pydantic models ──────────────────────────────────────────────────────────

class VendedorCreate(BaseModel):
    nombre: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    escala_comision: Optional[list] = None  # None → use DEFAULT_ESCALA


class VendedorUpdate(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    escala_comision: Optional[list] = None
    activo: Optional[bool] = None


class AsignarVendedor(BaseModel):
    vendedor_id: Optional[int] = None  # None = quitar asignación
    scope: str = "todas"  # "todas" = todas las facturas | "adelante" = solo nuevas


class AsignarPendiente(BaseModel):
    factura_ids: list          # list of invoice IDs
    cliente_id_xubio: Optional[str] = None
    vendedor_id: int
    permanente: bool = True    # if True, save client→vendor mapping for future invoices


class FacturaManual(BaseModel):
    numero: str
    fecha_emision: str          # YYYY-MM-DD
    fecha_cobro: Optional[str] = None
    cliente_nombre: str
    vendedor_id: Optional[int] = None
    neto: float
    iva: float = 0.0
    tipo: str = "Factura"
    estado: str = "cobrada"


class ConfigUpdate(BaseModel):
    xubio_client_id: Optional[str] = None
    xubio_client_secret: Optional[str] = None


class ReumenRequest(BaseModel):
    mes: int
    anio: int
    notas: Optional[str] = None
    fecha_hasta: Optional[str] = None  # YYYY-MM-DD corte opcional


class MarcarPagadaRequest(BaseModel):
    fecha_pago: str  # YYYY-MM-DD


# ── Vendedores ────────────────────────────────────────────────────────────────

@app.get("/api/vendedores")
def listar_vendedores():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vendedores ORDER BY activo DESC, nombre"
        ).fetchall()
    result = []
    for r in rows:
        v = dict(r)
        v["escala_comision"] = json.loads(v["escala_comision"])
        result.append(v)
    return result


@app.post("/api/vendedores", status_code=201)
def crear_vendedor(body: VendedorCreate):
    escala = body.escala_comision if body.escala_comision is not None else DEFAULT_ESCALA
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO vendedores (nombre, email, telefono, escala_comision, fecha_alta)
               VALUES (?, ?, ?, ?, ?)""",
            (body.nombre, body.email, body.telefono,
             json.dumps(escala), datetime.now().isoformat()),
        )
        vendedor_id = cur.lastrowid
        row = conn.execute("SELECT * FROM vendedores WHERE id = ?", (vendedor_id,)).fetchone()
    v = dict(row)
    v["escala_comision"] = json.loads(v["escala_comision"])
    return v


@app.get("/api/vendedores/{vid}")
def obtener_vendedor(vid: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendedores WHERE id = ?", (vid,)).fetchone()
    if not row:
        raise HTTPException(404, "Vendedor no encontrado")
    v = dict(row)
    v["escala_comision"] = json.loads(v["escala_comision"])
    return v


@app.put("/api/vendedores/{vid}")
def actualizar_vendedor(vid: int, body: VendedorUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendedores WHERE id = ?", (vid,)).fetchone()
        if not row:
            raise HTTPException(404, "Vendedor no encontrado")
        updates = {}
        if body.nombre is not None:    updates["nombre"] = body.nombre
        if body.email is not None:     updates["email"] = body.email
        if body.telefono is not None:  updates["telefono"] = body.telefono
        if body.activo is not None:    updates["activo"] = 1 if body.activo else 0
        if body.escala_comision is not None:
            updates["escala_comision"] = json.dumps(body.escala_comision)
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE vendedores SET {sets} WHERE id = ?",
                         [*updates.values(), vid])
        row = conn.execute("SELECT * FROM vendedores WHERE id = ?", (vid,)).fetchone()
    v = dict(row)
    v["escala_comision"] = json.loads(v["escala_comision"])
    return v


@app.delete("/api/vendedores/{vid}", status_code=204)
def eliminar_vendedor(vid: int):
    with get_conn() as conn:
        conn.execute("UPDATE vendedores SET activo = 0 WHERE id = ?", (vid,))


# ── Clientes ──────────────────────────────────────────────────────────────────

@app.get("/api/clientes")
def listar_clientes(buscar: str = "", page: int = 1, limit: int = 50):
    with get_conn() as conn:
        q = f"%{buscar}%"
        offset = (page - 1) * limit
        rows = conn.execute(
            """SELECT cv.*, v.nombre as vendedor_nombre
               FROM clientes_vendedor cv
               LEFT JOIN vendedores v ON cv.vendedor_id = v.id
               WHERE cv.nombre_cliente LIKE ? OR cv.cuit LIKE ?
               ORDER BY cv.nombre_cliente
               LIMIT ? OFFSET ?""",
            (q, q, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM clientes_vendedor WHERE nombre_cliente LIKE ? OR cuit LIKE ?",
            (q, q),
        ).fetchone()[0]
    return {"items": rows_to_list(rows), "total": total, "page": page}


@app.post("/api/clientes/{cliente_xubio_id}/asignar")
def asignar_vendedor_a_cliente(cliente_xubio_id: str, body: AsignarVendedor):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clientes_vendedor WHERE cliente_id_xubio = ?",
            (cliente_xubio_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Cliente no encontrado en el sistema")
        conn.execute(
            """UPDATE clientes_vendedor
               SET vendedor_id = ?, fecha_asignacion = ?
               WHERE cliente_id_xubio = ?""",
            (body.vendedor_id, datetime.now().isoformat(), cliente_xubio_id),
        )
        # Propagate to invoices according to scope
        if body.vendedor_id:
            if body.scope == "todas":
                conn.execute(
                    "UPDATE facturas SET vendedor_id = ? WHERE cliente_id_xubio = ?",
                    (body.vendedor_id, cliente_xubio_id),
                )
            else:  # "adelante" — solo facturas sin vendedor asignado
                conn.execute(
                    "UPDATE facturas SET vendedor_id = ? WHERE cliente_id_xubio = ? AND vendedor_id IS NULL",
                    (body.vendedor_id, cliente_xubio_id),
                )
    return {"ok": True}


# ── Facturas ──────────────────────────────────────────────────────────────────

@app.get("/api/facturas")
def listar_facturas(
    mes: Optional[int] = None,
    anio: Optional[int] = None,
    vendedor_id: Optional[int] = None,
    sin_vendedor: bool = False,
    page: int = 1,
    limit: int = 100,
):
    conditions = []
    params = []
    if mes:
        conditions.append("f.periodo_cobro_mes = ?")
        params.append(mes)
    if anio:
        conditions.append("f.periodo_cobro_anio = ?")
        params.append(anio)
    if vendedor_id:
        conditions.append("f.vendedor_id = ?")
        params.append(vendedor_id)
    if sin_vendedor:
        conditions.append("f.vendedor_id IS NULL")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * limit
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT f.*, v.nombre as vendedor_nombre
                FROM facturas f
                LEFT JOIN vendedores v ON f.vendedor_id = v.id
                {where}
                ORDER BY f.fecha_emision DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM facturas f {where}", params
        ).fetchone()[0]
    return {"items": rows_to_list(rows), "total": total, "page": page}


@app.post("/api/facturas/manual", status_code=201)
def agregar_factura_manual(body: FacturaManual):
    now = datetime.now()
    fecha_ref = body.fecha_cobro or body.fecha_emision
    try:
        dt = datetime.fromisoformat(fecha_ref[:10])
        mes, anio = dt.month, dt.year
    except Exception:
        mes, anio = now.month, now.year

    # Notas de Crédito are stored with negative amounts so they reduce the commission base
    if _is_nota_credito(body.tipo):
        neto = -abs(body.neto)
        iva  = -abs(body.iva)
        estado = "cobrada"  # always include NC in summaries
    else:
        neto = body.neto
        iva  = body.iva
        estado = body.estado

    xubio_id = f"MANUAL-{body.numero}-{body.fecha_emision}"
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM facturas WHERE xubio_id = ?", (xubio_id,)).fetchone()
        if existing:
            raise HTTPException(400, f"Ya existe una factura manual con número {body.numero}")
        cur = conn.execute(
            """INSERT INTO facturas
               (xubio_id, numero, tipo, fecha_emision, fecha_cobro,
                cliente_nombre, vendedor_id, neto, iva, total,
                estado, periodo_cobro_mes, periodo_cobro_anio, synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (xubio_id, body.numero, body.tipo, body.fecha_emision, body.fecha_cobro,
             body.cliente_nombre, body.vendedor_id, neto, iva,
             neto + iva, estado, mes, anio, now.isoformat()),
        )
        return {"id": cur.lastrowid, "ok": True}


@app.post("/api/facturas/{fid}/asignar-vendedor")
def asignar_vendedor_a_factura(fid: int, body: AsignarVendedor):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
        if not row:
            raise HTTPException(404, "Factura no encontrada")
        conn.execute("UPDATE facturas SET vendedor_id = ? WHERE id = ?",
                     (body.vendedor_id, fid))
    return {"ok": True}


class MarcarCobradaRequest(BaseModel):
    fecha_cobro: str  # YYYY-MM-DD


class CobrarLoteRequest(BaseModel):
    ids: list
    fecha_cobro: str  # YYYY-MM-DD


@app.post("/api/facturas/cobrar-lote")
def cobrar_lote(body: CobrarLoteRequest):
    try:
        dt = datetime.fromisoformat(body.fecha_cobro[:10])
        mes, anio = dt.month, dt.year
    except Exception:
        raise HTTPException(400, "Fecha inválida, usar formato YYYY-MM-DD")
    ids = [int(i) for i in body.ids]
    if not ids:
        raise HTTPException(400, "Sin facturas para cobrar")
    ph = ",".join("?" * len(ids))
    with get_conn() as conn:
        r = conn.execute(
            f"""UPDATE facturas SET estado='cobrada', fecha_cobro=?,
                periodo_cobro_mes=?, periodo_cobro_anio=?
                WHERE id IN ({ph}) AND neto > 0 AND estado NOT IN ('cobrada','pagada')""",
            [body.fecha_cobro[:10], mes, anio, *ids],
        )
    return {"ok": True, "actualizadas": r.rowcount}


@app.get("/api/facturas/exportar")
def exportar_facturas_csv(
    mes: Optional[int] = None,
    anio: Optional[int] = None,
    vendedor_id: Optional[int] = None,
):
    conditions = ["f.estado IN ('cobrada','pagada','cancelada')"]
    params: list = []
    if mes:
        conditions.append("f.periodo_cobro_mes = ?")
        params.append(mes)
    if anio:
        conditions.append("f.periodo_cobro_anio = ?")
        params.append(anio)
    if vendedor_id:
        conditions.append("f.vendedor_id = ?")
        params.append(vendedor_id)
    where = "WHERE " + " AND ".join(conditions)

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT f.numero, f.tipo, f.fecha_emision, f.fecha_cobro,
                       f.cliente_nombre, f.neto, f.iva, f.total,
                       f.estado, f.periodo_cobro_mes, f.periodo_cobro_anio,
                       v.nombre as vendedor_nombre
                FROM facturas f
                LEFT JOIN vendedores v ON f.vendedor_id = v.id
                {where}
                ORDER BY f.periodo_cobro_anio, f.periodo_cobro_mes, f.fecha_cobro""",
            params,
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Número", "Tipo", "Fecha Emisión", "Fecha Cobro",
        "Cliente", "Neto", "IVA", "Total",
        "Estado", "Mes", "Año", "Vendedor",
    ])
    for r in rows:
        writer.writerow([
            r["numero"] or "", r["tipo"] or "",
            r["fecha_emision"] or "", r["fecha_cobro"] or "",
            r["cliente_nombre"] or "",
            r["neto"] or 0, r["iva"] or 0, r["total"] or 0,
            r["estado"] or "",
            _mes_nombre(r["periodo_cobro_mes"]) if r["periodo_cobro_mes"] else "",
            r["periodo_cobro_anio"] or "",
            r["vendedor_nombre"] or "Sin asignar",
        ])

    nombre_mes = _mes_nombre(mes) if mes else "todos"
    filename = f"comisiones_{nombre_mes}_{anio or 'todos'}.csv"
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),  # utf-8-sig = BOM for Excel
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/facturas/{fid}/cobrar")
def marcar_cobrada(fid: int, body: MarcarCobradaRequest):
    try:
        dt = datetime.fromisoformat(body.fecha_cobro[:10])
        mes, anio = dt.month, dt.year
    except Exception:
        raise HTTPException(400, "Fecha inválida, usar formato YYYY-MM-DD")
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM facturas WHERE id = ?", (fid,)).fetchone()
        if not row:
            raise HTTPException(404, "Factura no encontrada")
        conn.execute(
            """UPDATE facturas
               SET estado='cobrada', fecha_cobro=?, periodo_cobro_mes=?, periodo_cobro_anio=?
               WHERE id=?""",
            (body.fecha_cobro[:10], mes, anio, fid),
        )
    return {"ok": True}


# ── Pendientes (facturas sin vendedor) ───────────────────────────────────────

@app.get("/api/pendientes")
def listar_pendientes():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT COALESCE(cliente_id_xubio, 'sin-' || cliente_nombre) as grupo_id,
                      cliente_id_xubio,
                      cliente_nombre,
                      COUNT(*) as cant_facturas,
                      SUM(neto) as total_neto,
                      MAX(fecha_emision) as ultima_factura,
                      GROUP_CONCAT(id) as factura_ids_str
               FROM facturas
               WHERE vendedor_id IS NULL
               GROUP BY COALESCE(cliente_id_xubio, 'sin-' || cliente_nombre)
               ORDER BY total_neto DESC"""
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            ids = [int(i) for i in d.pop("factura_ids_str", "").split(",") if i]
            d["factura_ids"] = ids
            if ids:
                ph = ",".join("?" * len(ids))
                facturas = conn.execute(
                    f"SELECT id, numero, fecha_emision, neto, tipo FROM facturas WHERE id IN ({ph})",
                    ids,
                ).fetchall()
                d["facturas"] = rows_to_list(facturas)
            else:
                d["facturas"] = []
            result.append(d)
    return result


@app.post("/api/pendientes/asignar")
def asignar_pendiente(body: AsignarPendiente):
    now = datetime.now()
    ids = [int(i) for i in body.factura_ids]
    if not ids:
        raise HTTPException(400, "Sin facturas para asignar")
    with get_conn() as conn:
        ph = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE facturas SET vendedor_id = ? WHERE id IN ({ph})",
            [body.vendedor_id] + ids,
        )
        if body.permanente and body.cliente_id_xubio:
            nombre_row = conn.execute(
                "SELECT cliente_nombre FROM facturas WHERE cliente_id_xubio = ? LIMIT 1",
                (body.cliente_id_xubio,),
            ).fetchone()
            nombre = nombre_row["cliente_nombre"] if nombre_row else "—"
            conn.execute(
                """INSERT OR REPLACE INTO clientes_vendedor
                   (cliente_id_xubio, nombre_cliente, vendedor_id, fecha_asignacion)
                   VALUES (?, ?, ?, ?)""",
                (body.cliente_id_xubio, nombre, body.vendedor_id, now.isoformat()),
            )
            # Propagate to any other unassigned invoices of this client
            conn.execute(
                "UPDATE facturas SET vendedor_id = ? WHERE cliente_id_xubio = ? AND vendedor_id IS NULL",
                (body.vendedor_id, body.cliente_id_xubio),
            )
    return {"ok": True}


# ── Resúmenes ─────────────────────────────────────────────────────────────────

def _add_pendiente(d: dict) -> dict:
    """Agrega comision_pendiente = comision_calculada − adelantos ya pagados."""
    d["comision_pendiente"] = round(
        (d.get("comision_calculada") or 0) - (d.get("adelantos_pagados") or 0), 2
    )
    return d


@app.get("/api/resumenes")
def listar_resumenes(vendedor_id: Optional[int] = None):
    with get_conn() as conn:
        cond = "WHERE r.vendedor_id = ?" if vendedor_id else ""
        params = [vendedor_id] if vendedor_id else []
        rows = conn.execute(
            f"""SELECT r.*, v.nombre as vendedor_nombre
                FROM resumenes r
                JOIN vendedores v ON r.vendedor_id = v.id
                {cond}
                ORDER BY r.periodo_anio DESC, r.periodo_mes DESC, v.nombre""",
            params,
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("escala_aplicada"):
            d["escala_aplicada"] = json.loads(d["escala_aplicada"])
        if d.get("detalle_facturas"):
            d["detalle_facturas"] = json.loads(d["detalle_facturas"])
        result.append(_add_pendiente(d))
    return result


@app.post("/api/resumenes")
def generar_resumen(body: ReumenRequest, vendedor_id: Optional[int] = None):
    """Generate and save summaries for one or all vendors."""
    with get_conn() as conn:
        if vendedor_id:
            vends = conn.execute(
                "SELECT * FROM vendedores WHERE id = ? AND activo = 1", (vendedor_id,)
            ).fetchall()
        else:
            vends = conn.execute(
                "SELECT * FROM vendedores WHERE activo = 1 ORDER BY nombre"
            ).fetchall()

        results = []
        for v in vends:
            escala = json.loads(v["escala_comision"])
            if body.fecha_hasta:
                fecha_desde = f"{body.anio}-{body.mes:02d}-01"
                facturas = conn.execute(
                    """SELECT * FROM facturas
                       WHERE vendedor_id = ?
                         AND fecha_cobro >= ? AND fecha_cobro <= ?
                         AND estado IN ('cobrada', 'pagada', 'cancelada')""",
                    (v["id"], fecha_desde, body.fecha_hasta),
                ).fetchall()
            else:
                facturas = conn.execute(
                    """SELECT * FROM facturas
                       WHERE vendedor_id = ?
                         AND periodo_cobro_mes = ?
                         AND periodo_cobro_anio = ?
                         AND estado IN ('cobrada', 'pagada', 'cancelada')""",
                    (v["id"], body.mes, body.anio),
                ).fetchall()

            total_neto = sum(f["neto"] for f in facturas)
            cant = len(facturas)
            comision, pct = calcular_comision(total_neto, escala)
            detalle = [
                {
                    "numero": f["numero"],
                    "fecha_cobro": f["fecha_cobro"],
                    "cliente": f["cliente_nombre"],
                    "neto": f["neto"],
                }
                for f in facturas
            ]

            # Si es resumen final (sin corte), sumar adelantos ya pagados este mes
            adelantos_pagados = 0.0
            if not body.fecha_hasta:
                row_adel = conn.execute(
                    """SELECT COALESCE(SUM(comision_pagada), 0) as total
                       FROM adelantos_comision
                       WHERE vendedor_id = ? AND periodo_mes = ? AND periodo_anio = ?""",
                    (v["id"], body.mes, body.anio),
                ).fetchone()
                adelantos_pagados = row_adel["total"] or 0.0

            conn.execute(
                """INSERT OR REPLACE INTO resumenes
                   (vendedor_id, periodo_mes, periodo_anio, total_cobrado_neto,
                    comision_calculada, porcentaje_aplicado, escala_aplicada,
                    cant_facturas, detalle_facturas, notas, fecha_corte,
                    adelantos_pagados, fecha_generacion)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (v["id"], body.mes, body.anio, total_neto, comision, pct,
                 json.dumps(escala), cant, json.dumps(detalle),
                 body.notas, body.fecha_hasta, adelantos_pagados,
                 datetime.now().isoformat()),
            )
            comision_pendiente = round(comision - adelantos_pagados, 2)
            results.append({
                "vendedor_id": v["id"],
                "vendedor_nombre": v["nombre"],
                "periodo": f"{_mes_nombre(body.mes)} {body.anio}",
                "total_cobrado_neto": total_neto,
                "porcentaje_aplicado": pct,
                "comision_calculada": comision,
                "cant_facturas": cant,
                "adelantos_pagados": adelantos_pagados,
                "comision_pendiente": comision_pendiente,
            })
    return results


@app.post("/api/resumenes/{rid}/marcar-pagada")
def marcar_comision_pagada(rid: int, body: MarcarPagadaRequest):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM resumenes WHERE id = ?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "Resumen no encontrado")
        conn.execute(
            "UPDATE resumenes SET comision_pagada = 1, fecha_pago_comision = ? WHERE id = ?",
            (body.fecha_pago, rid),
        )
        # Si es un adelanto (tiene fecha_corte), registrarlo para descontarlo del resumen final
        if row["fecha_corte"]:
            conn.execute(
                """INSERT OR REPLACE INTO adelantos_comision
                   (vendedor_id, periodo_mes, periodo_anio, fecha_corte,
                    total_neto, comision_pagada, porcentaje_aplicado,
                    fecha_pago, notas, fecha_generacion)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["vendedor_id"], row["periodo_mes"], row["periodo_anio"],
                 row["fecha_corte"], row["total_cobrado_neto"], row["comision_calculada"],
                 row["porcentaje_aplicado"], body.fecha_pago, row["notas"],
                 datetime.now().isoformat()),
            )
    return {"ok": True}


@app.post("/api/resumenes/{rid}/desmarcar-pagada")
def desmarcar_comision_pagada(rid: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM resumenes WHERE id = ?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "Resumen no encontrado")
        conn.execute(
            "UPDATE resumenes SET comision_pagada = 0, fecha_pago_comision = NULL WHERE id = ?",
            (rid,),
        )
        # Si era un adelanto, eliminar el registro para que no descuente del resumen final
        if row["fecha_corte"]:
            conn.execute(
                """DELETE FROM adelantos_comision
                   WHERE vendedor_id = ? AND periodo_mes = ? AND periodo_anio = ? AND fecha_corte = ?""",
                (row["vendedor_id"], row["periodo_mes"], row["periodo_anio"], row["fecha_corte"]),
            )
    return {"ok": True}


@app.get("/api/resumenes/{rid}")
def obtener_resumen(rid: int):
    with get_conn() as conn:
        row = conn.execute(
            """SELECT r.*, v.nombre as vendedor_nombre
               FROM resumenes r JOIN vendedores v ON r.vendedor_id = v.id
               WHERE r.id = ?""",
            (rid,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Resumen no encontrado")
    d = dict(row)
    if d.get("escala_aplicada"):
        d["escala_aplicada"] = json.loads(d["escala_aplicada"])
    if d.get("detalle_facturas"):
        d["detalle_facturas"] = json.loads(d["detalle_facturas"])
    return _add_pendiente(d)


# ── Estadísticas ──────────────────────────────────────────────────────────────

@app.get("/api/estadisticas")
def estadisticas_generales(anio: int = None):
    anio = anio or datetime.now().year
    with get_conn() as conn:
        # Monthly sales per vendor for the year
        ventas_mes = conn.execute(
            """SELECT v.nombre as vendedor, f.periodo_cobro_mes as mes,
                      SUM(f.neto) as total_neto, COUNT(*) as cant_facturas
               FROM facturas f
               JOIN vendedores v ON f.vendedor_id = v.id
               WHERE f.periodo_cobro_anio = ?
                 AND f.estado IN ('cobrada', 'pagada', 'cancelada')
               GROUP BY f.vendedor_id, f.periodo_cobro_mes
               ORDER BY v.nombre, f.periodo_cobro_mes""",
            (anio,),
        ).fetchall()

        # YTD totals per vendor
        ytd = conn.execute(
            """SELECT v.nombre as vendedor, v.id as vendedor_id,
                      v.escala_comision,
                      SUM(f.neto) as total_neto, COUNT(*) as cant_facturas
               FROM facturas f
               JOIN vendedores v ON f.vendedor_id = v.id
               WHERE f.periodo_cobro_anio = ?
                 AND f.estado IN ('cobrada', 'pagada', 'cancelada')
               GROUP BY f.vendedor_id
               ORDER BY total_neto DESC""",
            (anio,),
        ).fetchall()

        # Saved commissions history
        historial = conn.execute(
            """SELECT r.periodo_mes, r.periodo_anio, r.total_cobrado_neto,
                      r.comision_calculada, r.porcentaje_aplicado,
                      v.nombre as vendedor
               FROM resumenes r JOIN vendedores v ON r.vendedor_id = v.id
               WHERE r.periodo_anio = ?
               ORDER BY r.periodo_mes, v.nombre""",
            (anio,),
        ).fetchall()

    ytd_list = []
    for r in ytd:
        d = dict(r)
        escala = json.loads(d.pop("escala_comision"))
        comision, pct = calcular_comision(d["total_neto"] or 0, escala)
        d["comision_estimada"] = comision
        d["porcentaje_estimado"] = pct
        ytd_list.append(d)

    return {
        "anio": anio,
        "ventas_por_mes": rows_to_list(ventas_mes),
        "ytd_por_vendedor": ytd_list,
        "historial_comisiones": rows_to_list(historial),
    }


@app.get("/api/estadisticas/{vid}")
def estadisticas_vendedor(vid: int, anio: int = None):
    anio = anio or datetime.now().year
    with get_conn() as conn:
        v = conn.execute("SELECT * FROM vendedores WHERE id = ?", (vid,)).fetchone()
        if not v:
            raise HTTPException(404, "Vendedor no encontrado")

        mensual = conn.execute(
            """SELECT periodo_cobro_mes as mes, SUM(neto) as total_neto,
                      COUNT(*) as cant_facturas
               FROM facturas
               WHERE vendedor_id = ? AND periodo_cobro_anio = ?
                 AND estado IN ('cobrada', 'pagada', 'cancelada')
               GROUP BY periodo_cobro_mes
               ORDER BY periodo_cobro_mes""",
            (vid, anio),
        ).fetchall()

        top_clientes = conn.execute(
            """SELECT cliente_nombre, SUM(neto) as total_neto, COUNT(*) as cant_facturas
               FROM facturas
               WHERE vendedor_id = ? AND periodo_cobro_anio = ?
                 AND estado IN ('cobrada', 'pagada', 'cancelada')
               GROUP BY cliente_id_xubio
               ORDER BY total_neto DESC
               LIMIT 10""",
            (vid, anio),
        ).fetchall()

        resumenes = conn.execute(
            """SELECT * FROM resumenes
               WHERE vendedor_id = ? AND periodo_anio = ?
               ORDER BY periodo_mes""",
            (vid, anio),
        ).fetchall()

    escala = json.loads(v["escala_comision"])
    mensual_data = []
    for m in mensual:
        d = dict(m)
        comision, pct = calcular_comision(d["total_neto"] or 0, escala)
        d["comision_estimada"] = comision
        d["porcentaje_estimado"] = pct
        d["mes_nombre"] = _mes_nombre(d["mes"])
        mensual_data.append(d)

    return {
        "vendedor": dict(v) | {"escala_comision": escala},
        "mensual": mensual_data,
        "top_clientes": rows_to_list(top_clientes),
        "resumenes_guardados": rows_to_list(resumenes),
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
def dashboard(mes: int = None, anio: int = None):
    now = datetime.now()
    mes = mes or now.month
    anio = anio or now.year

    with get_conn() as conn:
        vendedores = conn.execute(
            "SELECT * FROM vendedores WHERE activo = 1 ORDER BY nombre"
        ).fetchall()

        cards = []
        for v in vendedores:
            escala = json.loads(v["escala_comision"])
            totales = conn.execute(
                """SELECT SUM(neto) as total_neto, COUNT(*) as cant
                   FROM facturas
                   WHERE vendedor_id = ? AND periodo_cobro_mes = ? AND periodo_cobro_anio = ?
                     AND estado IN ('cobrada', 'pagada', 'cancelada')""",
                (v["id"], mes, anio),
            ).fetchone()
            total_neto = totales["total_neto"] or 0
            cant = totales["cant"] or 0
            comision, pct = calcular_comision(total_neto, escala)

            # Next tier info
            next_tier = None
            for tramo in sorted(escala, key=lambda x: x["desde"]):
                if total_neto < tramo["desde"]:
                    next_tier = tramo
                    break

            # Facturas emitidas (pendientes de cobro) in this period
            por_cobrar = conn.execute(
                """SELECT SUM(ABS(neto)) as total_neto, COUNT(*) as cant
                   FROM facturas
                   WHERE vendedor_id = ? AND periodo_cobro_mes = ? AND periodo_cobro_anio = ?
                     AND estado = 'emitida' AND neto > 0""",
                (v["id"], mes, anio),
            ).fetchone()

            cards.append({
                "vendedor_id": v["id"],
                "vendedor_nombre": v["nombre"],
                "total_cobrado_neto": total_neto,
                "cant_facturas": cant,
                "comision_calculada": comision,
                "porcentaje_aplicado": pct,
                "proximo_tramo": next_tier,
                "tiene_resumen_guardado": conn.execute(
                    "SELECT 1 FROM resumenes WHERE vendedor_id=? AND periodo_mes=? AND periodo_anio=?",
                    (v["id"], mes, anio),
                ).fetchone() is not None,
                "por_cobrar_neto": por_cobrar["total_neto"] or 0,
                "por_cobrar_cant": por_cobrar["cant"] or 0,
            })

        sin_vendedor = conn.execute(
            """SELECT COUNT(*) FROM facturas
               WHERE vendedor_id IS NULL AND periodo_cobro_mes = ? AND periodo_cobro_anio = ?""",
            (mes, anio),
        ).fetchone()[0]

        ultimo_sync = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "periodo": {"mes": mes, "anio": anio, "mes_nombre": _mes_nombre(mes)},
        "vendedores": cards,
        "facturas_sin_vendedor": sin_vendedor,
        "ultimo_sync": row_to_dict(ultimo_sync),
        "escala_default": DEFAULT_ESCALA,
    }


# ── Sincronización ────────────────────────────────────────────────────────────

def _mes_atras(now: datetime, delta: int) -> tuple:
    """Return (year, month) for `delta` months before `now`, handling year boundaries correctly."""
    total = now.year * 12 + now.month - 1 - delta
    return total // 12, total % 12 + 1


def _do_sync(xubio: XubioClient, meses_atras: int = 3):
    """Full sync: vendors, clients, invoices, cobranzas."""
    now = datetime.now()
    stats = {"facturas_nuevas": 0, "facturas_actualizadas": 0,
             "vendedores_nuevos": 0, "clientes_nuevos": 0, "cobranzas_aplicadas": 0}
    detalles = []

    with get_conn() as conn:
        # 1. Sync vendors
        try:
            vendedores_xubio = xubio.get_vendedores()
            for vx in vendedores_xubio:
                exists = conn.execute(
                    "SELECT id FROM vendedores WHERE xubio_id = ?", (vx["xubio_id"],)
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO vendedores (nombre, email, xubio_id, escala_comision, fecha_alta)
                           VALUES (?, ?, ?, ?, ?)""",
                        (vx["nombre"], vx.get("email", ""), vx["xubio_id"],
                         json.dumps(DEFAULT_ESCALA), now.isoformat()),
                    )
                    stats["vendedores_nuevos"] += 1
                    detalles.append(f"Vendedor nuevo: {vx['nombre']}")
        except Exception as e:
            detalles.append(f"Warn vendedores: {e}")

        # 2. Sync invoices + cobranzas for last N months
        import calendar
        for delta in range(meses_atras):
            a, m = _mes_atras(now, delta)
            last_day = calendar.monthrange(a, m)[1]
            fecha_desde = f"{a}-{m:02d}-01"
            fecha_hasta = f"{a}-{m:02d}-{last_day}"

            page = 1
            while True:
                try:
                    resp = xubio.get_comprobantes(fecha_desde, fecha_hasta, page)
                except Exception as e:
                    detalles.append(f"Error comprobantes {fecha_desde}: {e}")
                    break

                for c in resp["items"]:
                    # Determine vendor: from invoice, then from client mapping
                    vendedor_id = None
                    if c["vendedor_xubio_id"]:
                        vrow = conn.execute(
                            "SELECT id FROM vendedores WHERE xubio_id = ?",
                            (c["vendedor_xubio_id"],),
                        ).fetchone()
                        if vrow:
                            vendedor_id = vrow["id"]
                    if vendedor_id is None and c["cliente_id"]:
                        cv = conn.execute(
                            "SELECT vendedor_id FROM clientes_vendedor WHERE cliente_id_xubio = ?",
                            (c["cliente_id"],),
                        ).fetchone()
                        if cv:
                            vendedor_id = cv["vendedor_id"]

                    # Determine period from fecha_cobro or fecha_emision
                    fecha_ref = c["fecha_cobro"] or c["fecha_emision"] or ""
                    try:
                        dt = datetime.fromisoformat(fecha_ref[:10])
                        periodo_mes, periodo_anio = dt.month, dt.year
                    except Exception:
                        periodo_mes, periodo_anio = m, a

                    existing = conn.execute(
                        "SELECT id, estado, fecha_cobro, periodo_cobro_mes, periodo_cobro_anio FROM facturas WHERE xubio_id = ?",
                        (c["xubio_id"],)
                    ).fetchone()
                    if existing:
                        ex = dict(existing)
                        # Never downgrade from cobrada/pagada to emitida:
                        # if the API now says 'cobrada', take that (Xubio registered a payment).
                        # if the API still says 'emitida' but we already marked it cobrada, keep it.
                        if c["estado"] == "cobrada":
                            est_final      = "cobrada"
                            fc_final       = c["fecha_cobro"] or ex["fecha_cobro"]
                            mes_final      = periodo_mes
                            anio_final     = periodo_anio
                        elif ex["estado"] in ("cobrada", "pagada"):
                            est_final      = ex["estado"]
                            fc_final       = ex["fecha_cobro"]
                            mes_final      = ex["periodo_cobro_mes"]
                            anio_final     = ex["periodo_cobro_anio"]
                        else:
                            est_final      = c["estado"]
                            fc_final       = c["fecha_cobro"]
                            mes_final      = periodo_mes
                            anio_final     = periodo_anio

                        conn.execute(
                            """UPDATE facturas SET estado=?, fecha_cobro=?, neto=?, iva=?,
                                  total=?, vendedor_id=COALESCE(vendedor_id,?),
                                  periodo_cobro_mes=?, periodo_cobro_anio=?, synced_at=?
                               WHERE xubio_id=?""",
                            (est_final, fc_final, c["neto"], c["iva"],
                             c["total"], vendedor_id, mes_final, anio_final,
                             now.isoformat(), c["xubio_id"]),
                        )
                        stats["facturas_actualizadas"] += 1
                    else:
                        conn.execute(
                            """INSERT INTO facturas
                               (xubio_id, numero, tipo, fecha_emision, fecha_cobro,
                                cliente_id_xubio, cliente_nombre, vendedor_id, neto, iva,
                                total, estado, periodo_cobro_mes, periodo_cobro_anio, synced_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (c["xubio_id"], c["numero"], c["tipo"], c["fecha_emision"],
                             c["fecha_cobro"], c["cliente_id"], c["cliente_nombre"],
                             vendedor_id, c["neto"], c["iva"], c["total"], c["estado"],
                             periodo_mes, periodo_anio, now.isoformat()),
                        )
                        stats["facturas_nuevas"] += 1

                    # Auto-register new client
                    if c["cliente_id"] and c["cliente_nombre"]:
                        conn.execute(
                            """INSERT OR IGNORE INTO clientes_vendedor
                               (cliente_id_xubio, nombre_cliente, vendedor_id, fecha_asignacion)
                               VALUES (?, ?, ?, ?)""",
                            (c["cliente_id"], c["cliente_nombre"],
                             vendedor_id, now.isoformat() if vendedor_id else None),
                        )

                if page * 200 >= resp["total"]:
                    break
                page += 1

        # 3. Apply cobranzas to mark invoices as paid
        # cobranzaBean without params returns all cobranzas; we filter by date in Python.
        # For each cobranza we look for direct invoice_ids first, then fall back to
        # client+date matching (all unpaid invoices for that client emitted before payment date).
        try:
            a0, m0 = _mes_atras(now, meses_atras - 1)
            global_fd = f"{a0}-{m0:02d}-01"
            global_fh = now.date().isoformat()

            cob_resp = xubio.get_cobranzas(fecha_desde=global_fd, fecha_hasta=global_fh)
            for cob in cob_resp["items"]:
                fecha_cobro = cob["fecha"]
                if not fecha_cobro:
                    continue
                try:
                    dt_c = datetime.fromisoformat(fecha_cobro)
                    cob_mes, cob_anio = dt_c.month, dt_c.year
                except Exception:
                    continue

                if cob["invoice_ids"]:
                    # Direct match: cobranzaBean/{id} told us exactly which invoices
                    for inv_xubio_id in cob["invoice_ids"]:
                        r = conn.execute(
                            """UPDATE facturas SET estado='cobrada', fecha_cobro=?,
                               periodo_cobro_mes=?, periodo_cobro_anio=?
                               WHERE xubio_id=? AND estado NOT IN ('cobrada','pagada')""",
                            (fecha_cobro, cob_mes, cob_anio, inv_xubio_id),
                        )
                        stats["cobranzas_aplicadas"] += r.rowcount
                elif cob["cliente_id"]:
                    # Fallback: match all unpaid invoices for this client emitted on or before
                    # the cobranza date (typical pattern: client pays all outstanding at once)
                    r = conn.execute(
                        """UPDATE facturas SET estado='cobrada', fecha_cobro=?,
                           periodo_cobro_mes=?, periodo_cobro_anio=?
                           WHERE cliente_id_xubio=?
                             AND estado NOT IN ('cobrada','pagada')
                             AND tipo NOT LIKE '%Nota de Cr%'
                             AND fecha_emision <= ?""",
                        (fecha_cobro, cob_mes, cob_anio, cob["cliente_id"], fecha_cobro),
                    )
                    stats["cobranzas_aplicadas"] += r.rowcount

            detalles.append(
                f"Cobranzas: {len(cob_resp['items'])} procesadas, "
                f"{stats['cobranzas_aplicadas']} facturas marcadas cobradas"
            )
        except Exception as e:
            detalles.append(f"Warn cobranzas: {e}")

        conn.execute(
            """INSERT INTO sync_log (fecha, facturas_nuevas, facturas_actualizadas,
               vendedores_nuevos, clientes_nuevos, estado, detalle)
               VALUES (?,?,?,?,?,?,?)""",
            (now.isoformat(), stats["facturas_nuevas"], stats["facturas_actualizadas"],
             stats["vendedores_nuevos"], stats["clientes_nuevos"],
             "ok", "; ".join(detalles) or "Sync completado"),
        )

    return stats


_sync_running = False
_last_sync_result: dict = {}


def _run_sync_bg(xubio: XubioClient, meses_atras: int):
    global _sync_running, _last_sync_result
    try:
        _last_sync_result = _do_sync(xubio, meses_atras)
    except Exception as e:
        _last_sync_result = {"error": str(e)}
    finally:
        _sync_running = False


@app.post("/api/sincronizar")
def sincronizar(background_tasks: BackgroundTasks, meses_atras: int = 1):
    global _sync_running
    if _sync_running:
        raise HTTPException(409, "Ya hay una sincronización en curso")
    xubio = get_xubio()
    _sync_running = True
    background_tasks.add_task(_run_sync_bg, xubio, meses_atras)
    return {"status": "iniciado", "meses_atras": meses_atras}


@app.get("/api/sincronizar/estado")
def estado_sync():
    return {
        "corriendo": _sync_running,
        "ultimo_resultado": _last_sync_result,
    }


@app.get("/api/sync-log")
def sync_log(limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return rows_to_list(rows)


# ── Configuración ─────────────────────────────────────────────────────────────

@app.get("/api/config")
def obtener_config():
    client_id = get_config("xubio_client_id", "")
    secret = get_config("xubio_client_secret", "")
    return {
        "xubio_client_id": client_id,
        "xubio_configurado": bool(client_id and secret),
    }


@app.post("/api/config")
def guardar_config(body: ConfigUpdate):
    if body.xubio_client_id is not None:
        set_config("xubio_client_id", body.xubio_client_id)
    if body.xubio_client_secret is not None:
        set_config("xubio_client_secret", body.xubio_client_secret)
    return {"ok": True}


@app.post("/api/config/test")
def test_conexion_xubio():
    xubio = get_xubio()
    return xubio.test_connection()


@app.get("/api/debug/xubio")
def debug_xubio_raw(recurso: str = "comprobanteVentaBean", fecha_desde: str = None, fecha_hasta: str = None):
    """Return raw Xubio API response for a given resource (for debugging field names)."""
    xubio = get_xubio()
    from datetime import date
    today = date.today()
    if not fecha_desde:
        fecha_desde = f"{today.year}-{today.month:02d}-01"
    if not fecha_hasta:
        fecha_hasta = today.isoformat()

    def fmt_ar(d):
        parts = d.split("-")
        return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

    try:
        raw = xubio._get(recurso, {
            "fechaDesde": fmt_ar(fecha_desde),
            "fechaHasta": fmt_ar(fecha_hasta),
            "pagina": 1,
            "pageSize": 2,
        })
    except Exception as e:
        return {"error": str(e), "recurso": recurso}

    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw] if isinstance(raw, dict) else []))
    first = items[0] if isinstance(items, list) and items else items

    return {
        "recurso": recurso,
        "keys_respuesta": list(raw.keys()) if isinstance(raw, dict) else f"lista de {len(raw)} items",
        "keys_primer_item": list(first.keys()) if isinstance(first, dict) else "no es dict",
        "primer_item_completo": first,
        "segundo_item": items[1] if isinstance(items, list) and len(items) > 1 else None,
    }


@app.get("/api/debug/cobranza-probe")
def debug_cobranza_probe(fecha_desde: str = None, fecha_hasta: str = None):
    """Try many cobranza endpoint variants to find what works. Does NOT stop at first success."""
    from datetime import date
    xubio = get_xubio()
    today = date.today()
    fd_iso = fecha_desde or f"{today.year}-{today.month:02d}-01"
    fh_iso = fecha_hasta or today.isoformat()

    # Also try a wider range (last 6 months) in case there are no recent cobranzas
    fd_wide = f"{today.year - 1 if today.month < 7 else today.year}-{(today.month - 6) % 12 + 1 or 6:02d}-01"

    def fmt_ar(d):
        parts = d.split("-")
        return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

    fd_ar = fmt_ar(fd_iso)
    fh_ar = fmt_ar(fh_iso)
    fd_wide_ar = fmt_ar(fd_wide)

    base_params = {"fechaDesde": fd_ar, "fechaHasta": fh_ar}
    wide_params = {"fechaDesde": fd_wide_ar, "fechaHasta": fh_ar}

    combos = [
        # Most likely names based on Xubio's Bean pattern and docs
        ("cobranza",              {}),
        ("cobranza",              base_params),
        ("cobranza",              wide_params),
        ("cobranzaBean",          {}),
        ("cobranzaBean",          base_params),
        ("reciboBean",            base_params),
        ("reciboBean",            {}),
        ("recibo",                base_params),
        ("recibo",                {}),
        ("reciboDeCobranza",      base_params),
        ("ReciboDeCobranza",      base_params),
        ("recibos",               base_params),
        ("cobranzas",             base_params),
        ("cobros",                base_params),
        ("cobro",                 base_params),
        ("pago",                  base_params),
        ("pagos",                 base_params),
        ("ordenDeCobro",          base_params),
        ("OrdenDeCobro",          base_params),
        ("ordenDeCobroBean",      base_params),
        ("ReciboCobro",           base_params),
        ("reciboCobranza",        base_params),
        ("cobranzaVentaBean",     base_params),
        ("transaccionCobranza",   base_params),
    ]
    results = []
    for endpoint, params in combos:
        try:
            raw = xubio._get(endpoint, params or None)
            items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw] if isinstance(raw, dict) else []))
            first = items[0] if isinstance(items, list) and items else items
            results.append({
                "ok": True,
                "endpoint": endpoint,
                "params": params,
                "total": len(raw) if isinstance(raw, list) else raw.get("total", "?"),
                "keys_primer_item": list(first.keys()) if isinstance(first, dict) else str(first)[:100],
                "primer_item": first,
            })
        except Exception as e:
            err = str(e)[:150]
            results.append({"ok": False, "endpoint": endpoint, "params": params, "error": err})
    return results


@app.get("/api/debug/cobranza-id/{cobranza_id}")
def debug_cobranza_por_id(cobranza_id: str):
    """Try to fetch a cobranza by its ID directly, testing multiple endpoint variants."""
    xubio = get_xubio()
    results = []
    for ep in ("cobranza", "cobranzaBean", "reciboBean", "recibo", "reciboDeCobranza",
               "ReciboCobro", "ordenDeCobro"):
        try:
            raw = xubio._get(f"{ep}/{cobranza_id}")
            results.append({"ok": True, "endpoint": f"{ep}/{cobranza_id}", "datos": raw})
        except Exception as e:
            results.append({"ok": False, "endpoint": f"{ep}/{cobranza_id}", "error": str(e)[:120]})
    return results


@app.get("/api/debug/xubio-id/{xubio_id}")
def debug_xubio_por_id(xubio_id: str, recurso: str = "comprobanteVentaBean"):
    """Fetch a single Xubio record by ID to see its full field set."""
    xubio = get_xubio()
    try:
        raw = xubio._get(f"{recurso}/{xubio_id}")
        return {
            "recurso": f"{recurso}/{xubio_id}",
            "keys": list(raw.keys()) if isinstance(raw, dict) else "lista",
            "datos": raw,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/debug/xubio-endpoint")
def debug_probar_endpoint(nombre: str, fecha_desde: str = None, fecha_hasta: str = None):
    """Try an arbitrary Xubio endpoint by name and return its raw response."""
    xubio = get_xubio()
    from datetime import date
    today = date.today()
    fd = fecha_desde or f"{today.year}-{today.month:02d}-01"
    fh = fecha_hasta or today.isoformat()

    def fmt_ar(d):
        parts = d.split("-")
        return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

    try:
        raw = xubio._get(nombre, {"fechaDesde": fmt_ar(fd), "fechaHasta": fmt_ar(fh), "pagina": 1, "pageSize": 2})
        items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw] if isinstance(raw, dict) else []))
        first = items[0] if isinstance(items, list) and items else items
        return {
            "ok": True, "endpoint": nombre,
            "keys_respuesta": list(raw.keys()) if isinstance(raw, dict) else f"lista de {len(raw)} items",
            "keys_primer_item": list(first.keys()) if isinstance(first, dict) else str(first)[:200],
            "primer_item_completo": first,
        }
    except Exception as e:
        return {"ok": False, "endpoint": nombre, "error": str(e)}


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def frontend():
    html_path = (Path(__file__).parent / "index.html")
    return html_path.read_text(encoding="utf-8")
