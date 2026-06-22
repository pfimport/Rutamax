import requests
from datetime import datetime, timedelta
from typing import Optional


TOKEN_URL = "https://xubio.com/API/1.1/TokenEndpoint"
API_BASE = "https://xubio.com/API/1.1"

# Field name mappings — adjust here if Xubio returns different names
FIELD_MAP_COMPROBANTE = {
    # comprobante field in Bean API is the numeric ID
    "id":             ["comprobante", "id", "idcomprobante", "comprobante_id", "transaccionid"],
    "numero":         ["numero", "nrocomprobante", "numero_comprobante", "externalId"],
    # tipo: numeric code — 1=Factura, 2=ND, 3=NC (see _TIPO_CODES)
    "tipo":           ["tipo", "tipocomprobante", "tipo_comprobante"],
    # letra: A/B/C — separate field if present
    "letra":          ["letra", "tipoLetra", "tipo_letra"],
    "fecha_emision":  ["fechaDesde", "fecha", "fecha_emision", "fechaemision"],
    "fecha_cobro":    ["fecha_cobro", "fechacobro", "fecha_pago"],
    "estado":         ["estado", "estado_pago", "estadopago"],
    # cliente is a nested object in Bean API: {ID, nombre, codigo, id}
    # handled specially in get_comprobantes()
    "cliente_id":     ["cliente_id", "idcliente", "clienteid"],
    "cliente_nombre": ["nombre_cliente", "razon_social"],
    "neto":           ["neto", "importe_neto", "importe_gravado", "gravado"],
    "iva":            ["iva", "importe_iva", "total_iva"],
    "total":          ["total", "importe_total", "monto_total"],
    "vendedor_id":    ["vendedor_id", "idvendedor"],
    "vendedor_nombre":["nombre_vendedor", "vendedor_nombre"],
}

FIELD_MAP_CLIENTE = {
    "id":           ["id", "idcliente", "cliente_id"],
    "nombre":       ["nombre", "razon_social", "nombre_cliente", "denominacion"],
    "cuit":         ["cuit", "cuit_cuil", "documento"],
    "email":        ["email", "mail", "correo"],
}

FIELD_MAP_VENDEDOR = {
    "id":     ["id", "idvendedor", "vendedor_id"],
    "nombre": ["nombre", "nombre_vendedor", "apellido_nombre"],
    "email":  ["email", "mail"],
}

FIELD_MAP_COBRANZA = {
    # numeroRecibo confirmed from Xubio API docs; also try legacy field names
    "id":                  ["numeroRecibo", "id", "idcobranza", "cobranza_id", "id_recibo",
                            "idrecibo", "numerocobranza", "nrocobranza", "numero"],
    "fecha":               ["fecha", "fecha_cobro", "fecha_cobranza", "fecha_recibo", "fechacobro"],
    # The field linking cobranza → invoice is still unconfirmed from docs;
    # try all likely names (flat string, list, or nested object handled in get_cobranzas)
    "numero_comprobante":  ["aplicacion", "aplicaciones", "comprobantesAplicados",
                            "numero_comprobante", "nrocomprobante", "comprobante",
                            "numerocomprobante", "nrocomprobanteaplicado",
                            "comprobante_id", "id_comprobante", "idcomprobante"],
    # cliente is a nested object in cobranzaBean: {ID, nombre, codigo, id}
    # handled specially in get_cobranzas(); these are fallback flat-field names
    "cliente_nombre":      ["nombre_cliente", "nombrecliente", "razonsocial", "cliente"],
    "cliente_id":          ["cliente_id", "idcliente", "id_cliente"],
    "monto":               ["importe", "monto", "total", "monto_cobrado", "importetotal"],
}


def _extract(obj: dict, field_map_entry: list, default=None):
    for key in field_map_entry:
        if key in obj:
            return obj[key]
    return default


def _parse_fecha(s: str) -> str:
    """Normalize to YYYY-MM-DD accepting both DD/MM/YYYY and YYYY-MM-DD."""
    if not s:
        return ""
    parts = s.split("/")
    if len(parts) == 3:          # DD/MM/YYYY → YYYY-MM-DD
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return s[:10]                # already YYYY-MM-DD (or trim time)


# Tipo codes from GET /comprobanteVentaBean docs:
# 1=Factura, 2=Nota de Débito, 3=Nota de Crédito, 4=Recibo, 5=Informe Diario de Cierre
# The A/B/C letter comes from a separate field (letra/tipoLetra) if present.
_TIPO_CODES = {
    "1": "Factura",
    "2": "Nota de Débito",
    "3": "Nota de Crédito",
    "4": "Recibo",
    "5": "Informe Diario de Cierre",
}


def _normalize_tipo(tipo, letra=None) -> str:
    if tipo is None:
        return ""
    s = str(tipo).strip()
    nombre = _TIPO_CODES.get(s, s)
    if letra:
        letra = str(letra).strip().upper()
        if letra and not nombre.endswith(letra):
            nombre = f"{nombre} {letra}"
    return nombre


def _is_nota_credito(tipo: str) -> bool:
    if not tipo:
        return False
    t = tipo.lower()
    return "nota de cr" in t or t.startswith("nc ") or t == "nc" or "/nc" in t or "n.c." in t


class XubioClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    def _ensure_token(self):
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return
        # Xubio uses client_id + secret_id (not client_secret)
        resp = requests.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "secret_id": self.client_secret,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)

    def _get(self, path: str, params: dict = None) -> dict:
        self._ensure_token()
        resp = requests.get(
            f"{API_BASE}/{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def test_connection(self) -> dict:
        try:
            self._ensure_token()
            return {"ok": True, "token": self._token[:10] + "..."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Vendedores ──────────────────────────────────────────────────────────

    def get_vendedores(self) -> list:
        # Xubio API docs list this as /vendorBean (Bean suffix pattern, same as all other endpoints)
        last_err = None
        for endpoint in ("vendorBean", "vendedor", "VendorBean", "Vendedor"):
            try:
                data = self._get(endpoint)
                break
            except Exception as e:
                last_err = e
                continue
        else:
            raise RuntimeError(f"Error al obtener vendedores de Xubio: {last_err}")

        raw = data if isinstance(data, list) else data.get("data", data.get("vendedores", []))
        result = []
        for v in raw:
            # vendedor may also have nested fields; handle flat for now
            result.append({
                "xubio_id": str(_extract(v, FIELD_MAP_VENDEDOR["id"], "")),
                "nombre":   _extract(v, FIELD_MAP_VENDEDOR["nombre"], "Sin nombre"),
                "email":    _extract(v, FIELD_MAP_VENDEDOR["email"], ""),
            })
        return result

    # ── Clientes ─────────────────────────────────────────────────────────────

    def get_clientes(self, page: int = 1) -> dict:
        # Xubio API uses clienteBean (consistent Bean suffix pattern)
        last_err = None
        for ep in ("clienteBean", "cliente", "ClienteBean"):
            try:
                data = self._get(ep, {"pagina": page, "pageSize": 100})
                break
            except Exception as e:
                last_err = e
        else:
            raise RuntimeError(f"Error al obtener clientes: {last_err}")
        raw = data if isinstance(data, list) else data.get("data", data.get("clientes", []))
        items = [
            {
                "xubio_id": str(_extract(c, FIELD_MAP_CLIENTE["id"], "")),
                "nombre":   _extract(c, FIELD_MAP_CLIENTE["nombre"], "Sin nombre"),
                "cuit":     _extract(c, FIELD_MAP_CLIENTE["cuit"], ""),
                "email":    _extract(c, FIELD_MAP_CLIENTE["email"], ""),
            }
            for c in raw
        ]
        total = data.get("total", data.get("totalItems", len(items))) if isinstance(data, dict) else len(items)
        return {"items": items, "total": total, "page": page}

    # ── Comprobantes de Venta ────────────────────────────────────────────────

    def _parse_comprobante_full(self, c: dict) -> dict:
        """Parse a full comprobanteVentaBean/{id} response into our standard dict.

        Confirmed field names from API (2026-06-22):
          numeroDocumento → human-readable number (e.g. "A-00006-00000220")
          fecha           → emission date YYYY-MM-DD
          importeGravado  → neto (net amount excl. IVA)
          importeImpuestos→ IVA amount
          importetotal    → total (all lowercase)
          transaccionid   → internal numeric ID
          tipo            → numeric code (1=Factura, 2=ND, 3=NC per docs)
          cliente         → nested object {ID, nombre, codigo, id}
          condicionDePago → 1=cuenta corriente, 2=contado (paid at emission)
          transaccionCobranzaItems → list of applied payments (empty if unpaid)
        """
        cliente_obj = c.get("cliente", {})
        if isinstance(cliente_obj, dict):
            cliente_id = str(cliente_obj.get("ID") or cliente_obj.get("id") or "")
            cliente_nombre = cliente_obj.get("nombre", "")
        else:
            cliente_id = ""
            cliente_nombre = ""

        vendedor_obj = c.get("vendedor")
        if isinstance(vendedor_obj, dict):
            vendedor_xubio_id = str(vendedor_obj.get("ID") or vendedor_obj.get("id") or "")
        else:
            vendedor_xubio_id = str(c.get("vendedor_id") or c.get("idvendedor") or "")

        tipo = _normalize_tipo(c.get("tipo", ""), c.get("letra") or c.get("tipoLetra"))
        neto  = float(c.get("importeGravado",   0) or 0)
        iva   = float(c.get("importeImpuestos", 0) or 0)
        total = float(c.get("importetotal",     0) or 0)

        # Determine payment status:
        # condicionDePago==2 → contado (paid immediately at emission)
        # transaccionCobranzaItems non-empty → one or more payments applied
        condicion_pago = c.get("condicionDePago", 1)
        cobranza_items = c.get("transaccionCobranzaItems") or []
        fecha_emision = _parse_fecha(c.get("fecha", "") or "")
        fecha_cobro = ""
        estado = "emitida"

        if condicion_pago == 2:
            estado = "cobrada"
            fecha_cobro = fecha_emision
        elif cobranza_items:
            estado = "cobrada"
            first_cob = cobranza_items[0] if isinstance(cobranza_items[0], dict) else {}
            fecha_cobro = _parse_fecha(str(first_cob.get("fecha", "") or "")) or fecha_emision

        if _is_nota_credito(tipo):
            neto, iva, total = -abs(neto), -abs(iva), -abs(total)
            estado = "cobrada"

        xubio_id = str(c.get("transaccionid", "") or "")
        numero = c.get("numeroDocumento", "") or xubio_id

        return {
            "xubio_id":          xubio_id,
            "numero":            numero,
            "tipo":              tipo,
            "fecha_emision":     fecha_emision,
            "fecha_cobro":       fecha_cobro,
            "estado":            estado,
            "cliente_id":        cliente_id,
            "cliente_nombre":    cliente_nombre,
            "neto":              neto,
            "iva":               iva,
            "total":             total,
            "vendedor_xubio_id": vendedor_xubio_id,
        }

    def get_comprobantes(self, fecha_desde: str, fecha_hasta: str, page: int = 1) -> dict:
        """Get invoices for a date range.

        Step 1: List endpoint gives us the IDs (minimal data, no amounts).
        Step 2: Fetch each invoice individually via comprobanteVentaBean/{id}
                to get importeGravado/importeImpuestos/importetotal/numeroDocumento
                and transaccionCobranzaItems to determine payment status.
        """
        def fmt_ar(d):
            parts = d.split("-")
            return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

        fd_ar = fmt_ar(fecha_desde)
        fh_ar = fmt_ar(fecha_hasta)

        attempts = [
            ("comprobanteVentaBean", {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("comprobanteVentaBean", {"fechaDesde": fecha_desde, "fechaHasta": fecha_hasta, "pagina": page, "pageSize": 200}),
        ]
        last_err = None
        for endpoint, params in attempts:
            try:
                data = self._get(endpoint, params)
                break
            except Exception as e:
                last_err = e
                continue
        else:
            raise RuntimeError(f"No se pudo obtener comprobantes de Xubio: {last_err}")

        raw = data if isinstance(data, list) else data.get("data", data.get("comprobantes", []))
        total_r = data.get("total", data.get("totalItems", len(raw))) if isinstance(data, dict) else len(raw)

        # Fetch full details for each invoice to get amounts and payment status
        items = []
        for c_min in raw:
            txid = str(c_min.get("transaccionid") or c_min.get("comprobante") or "")
            if not txid:
                continue
            try:
                c_full = self._get(f"comprobanteVentaBean/{txid}")
                items.append(self._parse_comprobante_full(c_full))
            except Exception:
                # Fallback: use minimal list data without amounts
                cliente_obj = c_min.get("cliente", {})
                if isinstance(cliente_obj, dict):
                    cl_id = str(cliente_obj.get("ID") or cliente_obj.get("id") or "")
                    cl_nombre = cliente_obj.get("nombre", "")
                else:
                    cl_id, cl_nombre = "", ""
                tipo = _normalize_tipo(c_min.get("tipo", ""))
                items.append({
                    "xubio_id": txid, "numero": txid, "tipo": tipo,
                    "fecha_emision": _parse_fecha(c_min.get("fecha") or c_min.get("fechaDesde") or ""),
                    "fecha_cobro": "", "estado": "emitida",
                    "cliente_id": cl_id, "cliente_nombre": cl_nombre,
                    "neto": 0.0, "iva": 0.0, "total": 0.0, "vendedor_xubio_id": "",
                })

        return {"items": items, "total": total_r, "page": page}

    # ── Cobranzas ────────────────────────────────────────────────────────────

    def get_cobranzas(self, fecha_desde: str = None, fecha_hasta: str = None) -> dict:
        """Fetch cobranzas from Xubio.

        CONFIRMED: cobranzaBean works WITHOUT date params (148 records returned).
        With date params it returns 404 — so we fetch everything and filter in Python.
        For each cobranza we try cobranzaBean/{id} to find which invoice IDs it applies.
        """
        try:
            data = self._get("cobranzaBean")
        except Exception as e:
            raise RuntimeError(f"No se pudo obtener cobranzas de Xubio: {e}")

        raw = data if isinstance(data, list) else data.get("data", data.get("cobranzas", []))

        items = []
        for c in raw:
            # cobranzaBean returns dates as ISO datetime: "2026-06-19T03:00:00.000+00:00"
            fecha_raw = str(c.get("fecha", "") or "")
            fecha = _parse_fecha(fecha_raw[:10])  # first 10 chars = YYYY-MM-DD

            # Client-side date filter (API doesn't support it)
            if fecha_desde and fecha and fecha < fecha_desde:
                continue
            if fecha_hasta and fecha and fecha > fecha_hasta:
                continue

            cob_id = str(c.get("transaccionid", "") or "")
            cliente_obj = c.get("cliente", {})
            if isinstance(cliente_obj, dict):
                cliente_id = str(cliente_obj.get("ID") or cliente_obj.get("id") or "")
                cliente_nombre = cliente_obj.get("nombre", "")
            else:
                cliente_id = ""
                cliente_nombre = ""

            # Fetch full cobranza detail to find which invoice IDs it applies
            invoice_ids = []
            if cob_id:
                try:
                    c_full = self._get(f"cobranzaBean/{cob_id}")
                    for field in ("comprobantesAplicados", "transaccionComprobantes",
                                  "aplicaciones", "comprobantes", "facturas",
                                  "transaccionItems", "itemsAplicados", "items"):
                        aplicados = c_full.get(field)
                        if isinstance(aplicados, list) and aplicados:
                            for ap in aplicados:
                                if isinstance(ap, dict):
                                    inv_id = (ap.get("transaccionid") or ap.get("transaccionId") or
                                              ap.get("id") or ap.get("comprobante") or
                                              ap.get("idcomprobante"))
                                    if inv_id:
                                        invoice_ids.append(str(inv_id))
                            if invoice_ids:
                                break
                except Exception:
                    pass

            # Payment total from instrument records
            instrumentos = c.get("transaccionInstrumentoDeCobro", [])
            monto = sum(float(i.get("importe", 0) or 0) for i in instrumentos
                        if isinstance(i, dict))

            items.append({
                "xubio_id":    cob_id,
                "fecha":       fecha,
                "cliente_id":  cliente_id,
                "cliente_nombre": cliente_nombre,
                "monto":       monto,
                "invoice_ids": invoice_ids,
                "numero":      c.get("numeroRecibo", cob_id),
            })

        total = data.get("total", len(raw)) if isinstance(data, dict) else len(raw)
        return {"items": items, "total": total}
