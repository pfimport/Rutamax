import requests
from datetime import datetime, timedelta
from typing import Optional


TOKEN_URL = "https://xubio.com/API/1.1/TokenEndpoint"
API_BASE = "https://xubio.com/API/1.1"

# Field name mappings — adjust here if Xubio returns different names
FIELD_MAP_COMPROBANTE = {
    "id":             ["id", "idcomprobante", "comprobante_id"],
    "numero":         ["numero", "nrocomprobante", "numero_comprobante"],
    "tipo":           ["tipo", "tipocomprobante", "tipo_comprobante"],
    "fecha_emision":  ["fecha", "fecha_emision", "fechaemision"],
    "fecha_cobro":    ["fecha_cobro", "fechacobro", "fecha_pago"],
    "estado":         ["estado", "estado_pago", "estadopago"],
    "cliente_id":     ["cliente_id", "idcliente", "clienteid"],
    "cliente_nombre": ["nombre_cliente", "cliente", "razon_social"],
    "neto":           ["neto", "importe_neto", "importe_gravado", "gravado"],
    "iva":            ["iva", "importe_iva", "total_iva"],
    "total":          ["total", "importe_total", "monto_total"],
    "vendedor_id":    ["vendedor_id", "idvendedor", "vendedor"],
    "vendedor_nombre":["vendedor", "nombre_vendedor", "vendedor_nombre"],
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
    "id":                  ["id", "idcobranza", "cobranza_id", "id_recibo", "idrecibo",
                            "numerocobranza", "nrocobranza", "numero"],
    "fecha":               ["fecha", "fecha_cobro", "fecha_cobranza", "fecha_recibo", "fechacobro"],
    # Xubio links cobranza → invoice by the human-readable invoice NUMBER (e.g. "A-00001-00004567")
    # The import template calls this field "Número de comprobante" / "Aplicación"
    "numero_comprobante":  ["aplicacion", "aplicaciones", "numero_comprobante", "nrocomprobante",
                            "comprobante", "numerocomprobante", "nrocomprobanteaplicado",
                            "comprobante_id", "id_comprobante", "idcomprobante"],
    "cliente_nombre":      ["cliente", "nombre_cliente", "nombrecliente", "razonsocial"],
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


# Xubio sometimes returns tipo as a numeric code (from import template: TIPO=1 → Factura A)
_TIPO_CODES = {
    "1": "Factura A", "2": "Factura B", "3": "Factura C", "4": "Factura M",
    "5": "Nota de Débito A", "6": "Nota de Débito B", "7": "Nota de Débito C",
    "8": "Nota de Crédito A", "9": "Nota de Crédito B", "10": "Nota de Crédito C",
    "11": "Factura E", "12": "Nota de Crédito E", "13": "Nota de Débito E",
    "51": "Factura A", "52": "Factura B", "53": "Factura C",
}


def _normalize_tipo(tipo) -> str:
    if tipo is None:
        return ""
    s = str(tipo).strip()
    return _TIPO_CODES.get(s, s)


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
        try:
            data = self._get("Vendedor")
            raw = data if isinstance(data, list) else data.get("data", data.get("vendedores", []))
            return [
                {
                    "xubio_id": str(_extract(v, FIELD_MAP_VENDEDOR["id"], "")),
                    "nombre":   _extract(v, FIELD_MAP_VENDEDOR["nombre"], "Sin nombre"),
                    "email":    _extract(v, FIELD_MAP_VENDEDOR["email"], ""),
                }
                for v in raw
            ]
        except Exception as e:
            raise RuntimeError(f"Error al obtener vendedores de Xubio: {e}")

    # ── Clientes ─────────────────────────────────────────────────────────────

    def get_clientes(self, page: int = 1) -> dict:
        data = self._get("Cliente", {"pagina": page, "pageSize": 100})
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

    def get_comprobantes(self, fecha_desde: str, fecha_hasta: str, page: int = 1) -> dict:
        # Xubio AR uses DD/MM/YYYY format and may call the endpoint differently
        def fmt_ar(d):
            # accepts YYYY-MM-DD, returns DD/MM/YYYY
            parts = d.split("-")
            return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

        fd_ar = fmt_ar(fecha_desde)
        fh_ar = fmt_ar(fecha_hasta)

        # Try multiple endpoint + param combinations until one works
        attempts = [
            ("ComprobanteVenta", {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("ComprobanteVenta", {"fechaDesde": fecha_desde, "fechaHasta": fecha_hasta, "pagina": page, "pageSize": 200}),
            ("Comprobante",      {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("ComprobanteVenta", {"fecha_desde": fd_ar, "fecha_hasta": fh_ar, "page": page}),
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
        items = []
        for c in raw:
            estado = _extract(c, FIELD_MAP_COMPROBANTE["estado"], "emitida")
            fecha_cobro = _extract(c, FIELD_MAP_COMPROBANTE["fecha_cobro"])
            fecha_emision = _extract(c, FIELD_MAP_COMPROBANTE["fecha_emision"], "")
            tipo = _normalize_tipo(_extract(c, FIELD_MAP_COMPROBANTE["tipo"], ""))

            neto  = float(_extract(c, FIELD_MAP_COMPROBANTE["neto"],  0) or 0)
            iva   = float(_extract(c, FIELD_MAP_COMPROBANTE["iva"],   0) or 0)
            total = float(_extract(c, FIELD_MAP_COMPROBANTE["total"], 0) or 0)

            # Notas de Crédito reduce the commission base → store as negative
            if _is_nota_credito(tipo):
                neto, iva, total = -abs(neto), -abs(iva), -abs(total)
                estado = "cobrada"  # ensure NCs are always included in summaries

            items.append({
                "xubio_id":          str(_extract(c, FIELD_MAP_COMPROBANTE["id"], "")),
                "numero":            _extract(c, FIELD_MAP_COMPROBANTE["numero"], ""),
                "tipo":              tipo,
                "fecha_emision":     _parse_fecha(_extract(c, FIELD_MAP_COMPROBANTE["fecha_emision"], "") or ""),
                "fecha_cobro":       _parse_fecha(_extract(c, FIELD_MAP_COMPROBANTE["fecha_cobro"]) or ""),
                "estado":            estado,
                "cliente_id":        str(_extract(c, FIELD_MAP_COMPROBANTE["cliente_id"], "")),
                "cliente_nombre":    _extract(c, FIELD_MAP_COMPROBANTE["cliente_nombre"], ""),
                "neto":              neto,
                "iva":               iva,
                "total":             total,
                "vendedor_xubio_id": str(_extract(c, FIELD_MAP_COMPROBANTE["vendedor_id"], "") or ""),
            })
        total_r = data.get("total", data.get("totalItems", len(items))) if isinstance(data, dict) else len(items)
        return {"items": items, "total": total_r, "page": page}

    # ── Cobranzas ────────────────────────────────────────────────────────────

    def get_cobranzas(self, fecha_desde: str, fecha_hasta: str, page: int = 1) -> dict:
        def fmt_ar(d):
            parts = d.split("-")
            return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else d

        fd_ar = fmt_ar(fecha_desde)
        fh_ar = fmt_ar(fecha_hasta)

        attempts = [
            ("Cobranza",        {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("ReciboCobro",     {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("ReciboCobranza",  {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("CobranzaVenta",   {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
            ("Cobro",           {"fechaDesde": fd_ar, "fechaHasta": fh_ar, "pagina": page, "pageSize": 200}),
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
            raise RuntimeError(f"No se pudo obtener cobranzas de Xubio: {last_err}")

        raw = data if isinstance(data, list) else data.get(
            "data", data.get("cobranzas", data.get("cobros", data.get("recibos", [])))
        )
        items = []
        for c in raw:
            fecha_raw  = _extract(c, FIELD_MAP_COBRANZA["fecha"], "")
            # The link is by invoice number ("Aplicación" in Xubio's model, e.g. "A-00001-00004567")
            # It may be a string, a list, or a nested object
            nro_comp = _extract(c, FIELD_MAP_COBRANZA["numero_comprobante"], "")
            if isinstance(nro_comp, list):
                nro_comp = nro_comp[0] if nro_comp else ""
            if isinstance(nro_comp, dict):
                nro_comp = (nro_comp.get("numero") or nro_comp.get("id")
                            or nro_comp.get("idcomprobante") or "")
            items.append({
                "xubio_id":          str(_extract(c, FIELD_MAP_COBRANZA["id"], "")),
                "fecha":             _parse_fecha(str(fecha_raw)),
                "numero_comprobante": str(nro_comp or "").strip(),
                "cliente_nombre":    _extract(c, FIELD_MAP_COBRANZA["cliente_nombre"], ""),
                "cliente_id":        str(_extract(c, FIELD_MAP_COBRANZA["cliente_id"], "") or ""),
                "monto":             float(_extract(c, FIELD_MAP_COBRANZA["monto"], 0) or 0),
            })
        total_c = data.get("total", data.get("totalItems", len(items))) if isinstance(data, dict) else len(items)
        return {"items": items, "total": total_c, "page": page}
