"""
database/db.py
--------------
SQLite con schema compatible con SQL Server.
Para migrar a producción: cambiar get_connection().
"""

import sqlite3
import json
import os
from typing import Optional
import hashlib
import secrets
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "arcfast.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: str = None) -> tuple:
    if not salt:
        salt = secrets.token_hex(32)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    return hashed, salt


def init_db():
    conn = get_connection()
    cur  = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        email           TEXT NOT NULL UNIQUE,
        password_hash   TEXT NOT NULL,
        salt            TEXT NOT NULL,
        rol             TEXT NOT NULL CHECK(rol IN ('arca','cliente')),
        empresa         TEXT,
        activo          INTEGER DEFAULT 1,
        fecha_creacion  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS planes (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        url_portal          TEXT NOT NULL,
        plataforma_origen   TEXT,
        plataforma_destino  TEXT,
        objetivo            TEXT,
        plan_json           TEXT NOT NULL,
        version             INTEGER DEFAULT 1,
        activo              INTEGER DEFAULT 1,
        fecha_creacion      TEXT NOT NULL,
        fecha_actualizacion TEXT,
        usuario_id          INTEGER,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS mapeos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        url_portal          TEXT NOT NULL,
        campo_origen        TEXT NOT NULL,
        campo_destino       TEXT NOT NULL,
        confianza_inicial   REAL NOT NULL,
        confianza_actual    REAL NOT NULL,
        n_confirmaciones    INTEGER DEFAULT 0,
        n_correcciones      INTEGER DEFAULT 0,
        fecha_creacion      TEXT NOT NULL,
        fecha_actualizacion TEXT
    );

    CREATE TABLE IF NOT EXISTS sesiones (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha               TEXT NOT NULL,
        usuario_id          INTEGER,
        email_usuario       TEXT,
        empresa             TEXT,
        url_portal          TEXT,
        plataforma_origen   TEXT,
        plataforma_destino  TEXT,
        n_pasos             INTEGER DEFAULT 0,
        n_exitosos          INTEGER DEFAULT 0,
        n_errores           INTEGER DEFAULT 0,
        n_advertencias      INTEGER DEFAULT 0,
        duracion_seg        REAL,
        plan_id             INTEGER,
        resultado_json      TEXT,
        FOREIGN KEY (plan_id)     REFERENCES planes(id),
        FOREIGN KEY (usuario_id)  REFERENCES usuarios(id)
    );

    CREATE TABLE IF NOT EXISTS errores (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sesion_id   INTEGER NOT NULL,
        paso        INTEGER,
        accion      TEXT,
        descripcion TEXT,
        fecha       TEXT NOT NULL,
        FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
    );

    CREATE TABLE IF NOT EXISTS pedidos (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        sesion_id       INTEGER,
        fecha           TEXT NOT NULL,
        comercio        TEXT,
        cliente         TEXT,
        zip             TEXT,
        envio           TEXT,
        productos_json  TEXT,
        subtotal        REAL DEFAULT 0,
        impuestos       REAL DEFAULT 0,
        total           REAL DEFAULT 0,
        ticket_enviado  INTEGER DEFAULT 0,
        FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
    );
    """)
    conn.commit()

    # Seed: usuario Arca y usuario demo cliente
    cur.execute("SELECT COUNT(*) as n FROM usuarios")
    if cur.fetchone()["n"] == 0:
        now = datetime.now().isoformat()
        for email, pwd, rol, empresa in [
            ("arca@arcacontinental.mx",  "arca2026",    "arca",    "Arca Continental"),
            ("walmart@walmart.com.mx",   "cliente2026", "cliente", "Walmart México"),
            ("soriana@soriana.com",      "cliente2026", "cliente", "Soriana"),
        ]:
            h, s = hash_password(pwd)
            cur.execute(
                "INSERT INTO usuarios (email,password_hash,salt,rol,empresa,fecha_creacion) VALUES (?,?,?,?,?,?)",
                (email, h, s, rol, empresa, now)
            )
        conn.commit()

    conn.close()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> Optional[dict]:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE email=? AND activo=1", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    hashed, _ = hash_password(password, row["salt"])
    if hashed != row["password_hash"]:
        return None
    return dict(row)


def registrar_usuario(email: str, password: str, rol: str, empresa: str) -> dict:
    conn = get_connection()
    cur  = conn.cursor()
    h, s = hash_password(password)
    now  = datetime.now().isoformat()
    try:
        cur.execute(
            "INSERT INTO usuarios (email,password_hash,salt,rol,empresa,fecha_creacion) VALUES (?,?,?,?,?,?)",
            (email, h, s, rol, empresa, now)
        )
        conn.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError("El email ya está registrado")
    conn.close()
    return {"id": uid, "email": email, "rol": rol, "empresa": empresa}


# ─── Planes ───────────────────────────────────────────────────────────────────

def guardar_plan(plan: dict, usuario_id: int = None) -> int:
    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()
    cur.execute("UPDATE planes SET activo=0 WHERE url_portal=?", (plan.get("url_portal",""),))
    cur.execute("""
        INSERT INTO planes (url_portal,plataforma_origen,plataforma_destino,
                            objetivo,plan_json,activo,fecha_creacion,usuario_id)
        VALUES (?,?,?,?,?,1,?,?)
    """, (plan.get("url_portal",""), plan.get("plataforma_origen",""),
          plan.get("plataforma_destino",""), plan.get("objetivo",""),
          json.dumps(plan, ensure_ascii=False), now, usuario_id))
    plan_id = cur.lastrowid
    for campo in plan.get("mapeo_campos", []):
        p = campo.get("confianza", 1.0)
        cur.execute("""
            INSERT INTO mapeos (url_portal,campo_origen,campo_destino,
                                confianza_inicial,confianza_actual,fecha_creacion)
            VALUES (?,?,?,?,?,?)
        """, (plan.get("url_portal",""), campo.get("campo_origen",""),
              campo.get("campo_destino",""), p, p, now))
    conn.commit()
    conn.close()
    return plan_id


def cargar_plan_activo(url_portal: str) -> Optional[dict]:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT plan_json FROM planes WHERE url_portal=? AND activo=1 ORDER BY id DESC LIMIT 1", (url_portal,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row["plan_json"]) if row else None


# ─── Sesiones ─────────────────────────────────────────────────────────────────

def guardar_sesion(plan: dict, resultados: list, email: str,
                   duracion_seg: float = None, plan_id: int = None,
                   usuario_id: int = None, empresa: str = None) -> int:
    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()
    ok   = sum(1 for r in resultados if r.get("estado") == "ok")
    err  = sum(1 for r in resultados if r.get("estado") == "error")
    warn = sum(1 for r in resultados if r.get("estado") == "advertencia")
    cur.execute("""
        INSERT INTO sesiones (fecha,usuario_id,email_usuario,empresa,url_portal,
                              plataforma_origen,plataforma_destino,
                              n_pasos,n_exitosos,n_errores,n_advertencias,
                              duracion_seg,plan_id,resultado_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (now, usuario_id, email, empresa,
          plan.get("url_portal",""), plan.get("plataforma_origen",""),
          plan.get("plataforma_destino",""),
          len(resultados), ok, err, warn,
          duracion_seg, plan_id,
          json.dumps(resultados, ensure_ascii=False)))
    sesion_id = cur.lastrowid
    for r in resultados:
        if r.get("estado") != "ok":
            cur.execute("""
                INSERT INTO errores (sesion_id,paso,accion,descripcion,fecha)
                VALUES (?,?,?,?,?)
            """, (sesion_id, r.get("paso"), r.get("accion",""),
                  str(r.get("datos_extraidos","")), now))
    conn.commit()
    conn.close()
    return sesion_id


# ─── Analytics para dashboard Arca ───────────────────────────────────────────

def obtener_historial(limit: int = 50) -> list:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT s.id, s.fecha, s.email_usuario, s.empresa, s.url_portal,
               s.plataforma_origen, s.plataforma_destino,
               s.n_pasos, s.n_exitosos, s.n_errores, s.duracion_seg
        FROM sesiones s ORDER BY s.id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def obtener_estadisticas() -> dict:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM sesiones")
    total = cur.fetchone()["total"]
    cur.execute("SELECT AVG(CAST(n_exitosos AS REAL)/NULLIF(n_pasos,0))*100 as tasa FROM sesiones")
    tasa = cur.fetchone()["tasa"] or 0
    cur.execute("SELECT COUNT(*) as total FROM planes WHERE activo=1")
    n_planes = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as total FROM usuarios WHERE rol='cliente' AND activo=1")
    n_clientes = cur.fetchone()["total"]
    cur.execute("""
        SELECT empresa, COUNT(*) as sesiones,
               AVG(CAST(n_exitosos AS REAL)/NULLIF(n_pasos,0))*100 as tasa_exito,
               SUM(n_errores) as total_errores
        FROM sesiones WHERE empresa IS NOT NULL
        GROUP BY empresa ORDER BY sesiones DESC
    """)
    por_cliente = [dict(r) for r in cur.fetchall()]
    cur.execute("""
        SELECT accion, COUNT(*) as total
        FROM errores GROUP BY accion ORDER BY total DESC LIMIT 10
    """)
    errores_por_accion = [dict(r) for r in cur.fetchall()]
    cur.execute("""
        SELECT DATE(fecha) as dia, COUNT(*) as sesiones,
               AVG(CAST(n_exitosos AS REAL)/NULLIF(n_pasos,0))*100 as tasa
        FROM sesiones GROUP BY dia ORDER BY dia DESC LIMIT 30
    """)
    por_dia = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "total_sesiones":    total,
        "tasa_exito_pct":    round(tasa, 1),
        "planes_activos":    n_planes,
        "clientes_activos":  n_clientes,
        "por_cliente":       por_cliente,
        "errores_por_accion": errores_por_accion,
        "por_dia":           por_dia,
    }


def guardar_pedido(datos_pedido: dict, sesion_id: int = None) -> int:
    """
    Persiste un pedido extraído del agente en la tabla pedidos.
    Retorna el id insertado.
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO pedidos
            (sesion_id, fecha, comercio, cliente, zip, envio,
             productos_json, subtotal, impuestos, total, ticket_enviado)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        sesion_id,
        datos_pedido.get("fecha", datetime.now().isoformat()),
        datos_pedido.get("comercio") or datos_pedido.get("objetivo", ""),
        datos_pedido.get("cliente", ""),
        datos_pedido.get("zip", ""),
        datos_pedido.get("envio", ""),
        json.dumps(datos_pedido.get("productos", []), ensure_ascii=False),
        float(datos_pedido.get("subtotal", 0)),
        float(datos_pedido.get("impuestos", 0)),
        float(datos_pedido.get("total", 0)),
        1 if datos_pedido.get("ticket_enviado") else 0,
    ))
    conn.commit()
    pedido_id = cur.lastrowid
    conn.close()
    return pedido_id


def obtener_pedidos(limit: int = 50) -> list:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, fecha, comercio, cliente, zip, envio,
               productos_json, subtotal, impuestos, total, ticket_enviado
        FROM pedidos ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        try:
            r["productos"] = json.loads(r.get("productos_json") or "[]")
        except Exception:
            r["productos"] = []
    return rows


init_db()
