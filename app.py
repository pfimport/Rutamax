import json
import asyncio
from datetime import datetime, date
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import (
    init_db, get_conn, row_to_dict, rows_to_list,
    calcular_comision, DEFAULT_ESCALA, get_config, set_config,
)
from xubio import XubioClient


# ── Helpers ──────────────────────────────────────────────────────────────────

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
        # Propagate to unassigned invoices of this client
        if body.vendedor_id:
            conn.execute(
                """UPDATE facturas SET vendedor_id = ?
                   WHERE cliente_id_xubio = ? AND vendedor_id IS NULL""",
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
             body.cliente_nombre, body.vendedor_id, body.neto, body.iva,
             body.neto + body.iva, body.estado, mes, anio, now.isoformat()),
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
        result.append(d)
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

            conn.execute(
                """INSERT OR REPLACE INTO resumenes
                   (vendedor_id, periodo_mes, periodo_anio, total_cobrado_neto,
                    comision_calculada, porcentaje_aplicado, escala_aplicada,
                    cant_facturas, detalle_facturas, notas, fecha_generacion)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (v["id"], body.mes, body.anio, total_neto, comision, pct,
                 json.dumps(escala), cant, json.dumps(detalle),
                 body.notas, datetime.now().isoformat()),
            )
            results.append({
                "vendedor_id": v["id"],
                "vendedor_nombre": v["nombre"],
                "periodo": f"{_mes_nombre(body.mes)} {body.anio}",
                "total_cobrado_neto": total_neto,
                "porcentaje_aplicado": pct,
                "comision_calculada": comision,
                "cant_facturas": cant,
            })
    return results


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
    return d


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

def _do_sync(xubio: XubioClient, meses_atras: int = 3):
    """Full sync: vendors, clients, invoices."""
    now = datetime.now()
    stats = {"facturas_nuevas": 0, "facturas_actualizadas": 0,
             "vendedores_nuevos": 0, "clientes_nuevos": 0}
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

        # 2. Sync invoices for last N months
        for delta in range(meses_atras):
            m = (now.month - delta - 1) % 12 + 1
            a = now.year - ((now.month - delta - 1) // 12)
            fecha_desde = f"{a}-{m:02d}-01"
            if m == 12:
                fecha_hasta = f"{a}-12-31"
            else:
                import calendar
                last_day = calendar.monthrange(a, m)[1]
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
                        "SELECT id FROM facturas WHERE xubio_id = ?", (c["xubio_id"],)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            """UPDATE facturas SET estado=?, fecha_cobro=?, neto=?, iva=?,
                                  total=?, vendedor_id=COALESCE(vendedor_id,?),
                                  periodo_cobro_mes=?, periodo_cobro_anio=?, synced_at=?
                               WHERE xubio_id=?""",
                            (c["estado"], c["fecha_cobro"], c["neto"], c["iva"],
                             c["total"], vendedor_id, periodo_mes, periodo_anio,
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


@app.post("/api/sincronizar")
def sincronizar(meses_atras: int = 1):
    global _sync_running
    if _sync_running:
        raise HTTPException(409, "Ya hay una sincronización en curso")
    xubio = get_xubio()
    _sync_running = True
    try:
        result = _do_sync(xubio, meses_atras)
    finally:
        _sync_running = False
    return result


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


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def frontend():
    html_path = (Path(__file__).parent / "index.html")
    return html_path.read_text(encoding="utf-8")
