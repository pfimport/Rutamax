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


def _extract(obj: dict, field_map_entry: list, default=None):
    for key in field_map_entry:
        if key in obj:
            return obj[key]
    return default


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
        data = self._get("ComprobanteVenta", {
            "fechaDesde": fecha_desde,
            "fechaHasta": fecha_hasta,
            "pagina": page,
            "pageSize": 200,
        })
        raw = data if isinstance(data, list) else data.get("data", data.get("comprobantes", []))
        items = []
        for c in raw:
            estado = _extract(c, FIELD_MAP_COMPROBANTE["estado"], "emitida")
            # Date for cobro period — use fecha_cobro if paid, else fecha_emision
            fecha_cobro = _extract(c, FIELD_MAP_COMPROBANTE["fecha_cobro"])
            fecha_emision = _extract(c, FIELD_MAP_COMPROBANTE["fecha_emision"], "")

            items.append({
                "xubio_id":       str(_extract(c, FIELD_MAP_COMPROBANTE["id"], "")),
                "numero":         _extract(c, FIELD_MAP_COMPROBANTE["numero"], ""),
                "tipo":           _extract(c, FIELD_MAP_COMPROBANTE["tipo"], ""),
                "fecha_emision":  fecha_emision,
                "fecha_cobro":    fecha_cobro,
                "estado":         estado,
                "cliente_id":     str(_extract(c, FIELD_MAP_COMPROBANTE["cliente_id"], "")),
                "cliente_nombre": _extract(c, FIELD_MAP_COMPROBANTE["cliente_nombre"], ""),
                "neto":           float(_extract(c, FIELD_MAP_COMPROBANTE["neto"], 0) or 0),
                "iva":            float(_extract(c, FIELD_MAP_COMPROBANTE["iva"], 0) or 0),
                "total":          float(_extract(c, FIELD_MAP_COMPROBANTE["total"], 0) or 0),
                "vendedor_xubio_id": str(_extract(c, FIELD_MAP_COMPROBANTE["vendedor_id"], "") or ""),
            })
        total = data.get("total", data.get("totalItems", len(items))) if isinstance(data, dict) else len(items)
        return {"items": items, "total": total, "page": page}
