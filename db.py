import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "facturas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo TEXT NOT NULL,
    proveedor TEXT,
    cuit TEXT,
    numero_factura TEXT,
    fecha TEXT,
    total TEXT,
    moneda TEXT,
    categoria TEXT,
    cuit_valido TEXT,
    duplicado TEXT,
    estado TEXT DEFAULT 'Pendiente',
    vencimiento TEXT,
    metodo_extraccion TEXT,
    subido_en TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

CATEGORIAS = ["Insumos", "Servicios", "Alquiler", "Impuestos", "Sueldos", "Mercaderia", "Otros"]
ESTADOS = ["Pendiente", "Pagada"]

EXTRA_COLUMNS = {
    "categoria": "TEXT",
    "cuit_valido": "TEXT",
    "duplicado": "TEXT",
    "estado": "TEXT DEFAULT 'Pendiente'",
    "vencimiento": "TEXT",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.execute(SCHEMA)
    for col, coltype in EXTRA_COLUMNS.items():
        try:
            conn.execute(f"ALTER TABLE facturas ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def find_duplicate(cuit: str, numero_factura: str, exclude_id: int | None = None) -> sqlite3.Row | None:
    if not cuit or not numero_factura:
        return None
    conn = get_conn()
    query = "SELECT * FROM facturas WHERE cuit = ? AND numero_factura = ?"
    params = [cuit, numero_factura]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    row = conn.execute(query, params).fetchone()
    conn.close()
    return row


def insert_factura(record: dict) -> int:
    conn = get_conn()
    cols = [
        "archivo", "proveedor", "cuit", "numero_factura", "fecha", "total", "moneda",
        "categoria", "cuit_valido", "duplicado", "estado", "vencimiento", "metodo_extraccion",
    ]
    values = [record.get(c) for c in cols]
    values[cols.index("estado")] = record.get("estado") or "Pendiente"
    cur = conn.execute(
        f"INSERT INTO facturas ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        values,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_all() -> list[sqlite3.Row]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM facturas ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def update_factura(row_id: int, fields: dict):
    if not fields:
        return
    conn = get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE facturas SET {set_clause} WHERE id = ?", [*fields.values(), row_id])
    conn.commit()
    conn.close()


def delete_factura(row_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM facturas WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()
