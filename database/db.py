"""
database/db.py
--------------
Base de datos SQLite con schema compatible con SQL Server.
Para migrar a producción: cambiar la conexión en get_connection().

SQL Server equivalente:
    pip install pyodbc
    conn = pyodbc.connect('DRIVER={SQL Server};SERVER=...;DATABASE=arcfast;')
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "arcfast.db")


def get_connection():
    """
    SQLite para demo. Para SQL Server reemplazar con:
        import pyodbc
        return pyodbc.connect('DRIVER={SQL Server};SERVER=tu_servidor;DATABASE=arcfast;Trusted_Connection=yes;')
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea las tablas si no existen."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.executescript("""
    -- Planes aprendidos por portal
    CREATE TABLE IF NOT EXISTS planes (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        url_portal       TEXT NOT NULL,
        plataforma_origen  TEXT,
        plataforma_destino TEXT,
        objetivo         TEXT,
        plan_json        TEXT NOT NULL,
        version          INTEGER DEFAULT 1,
        activo           INTEGER DEFAULT 1,
        fecha_creacion   TEXT NOT NULL,
        fecha_actualizacion TEXT
    );

    -- Mapeos de campos con confianza bayesiana actualizable
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

    -- Historial de ejecuciones
    CREATE TABLE IF NOT EXISTS sesiones (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha               TEXT NOT NULL,
        email_usuario       TEXT,
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
        FOREIGN KEY (plan_id) REFERENCES planes(id)
    );

    -- Errores específicos por sesión
    CREATE TABLE IF NOT EXISTS errores (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sesion_id   INTEGER NOT NULL,
        paso        INTEGER,
        accion      TEXT,
        descripcion TEXT,
        fecha       TEXT NOT NULL,
        FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
    );
    """)

    conn.commit()
    conn.close()
    print(f"  ✅ Base de datos inicializada en {DB_PATH}")


# ─── Planes ───────────────────────────────────────────────────────────────────

def guardar_plan(plan: dict) -> int:
    """Guarda un nuevo plan aprendido. Devuelve el ID."""
    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()

    # Desactivar planes anteriores del mismo portal
    cur.execute(
        "UPDATE planes SET activo=0 WHERE url_portal=?",
        (plan.get("url_portal", ""),)
    )

    cur.execute("""
        INSERT INTO planes (url_portal, plataforma_origen, plataforma_destino,
                            objetivo, plan_json, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (
        plan.get("url_portal", ""),
        plan.get("plataforma_origen", ""),
        plan.get("plataforma_destino", ""),
        plan.get("objetivo", ""),
        json.dumps(plan, ensure_ascii=False),
        now,
    ))

    plan_id = cur.lastrowid

    # Guardar mapeos individuales
    for campo in plan.get("mapeo_campos", []):
        p = campo.get("confianza", 1.0)
        cur.execute("""
            INSERT INTO mapeos (url_portal, campo_origen, campo_destino,
                                confianza_inicial, confianza_actual,
                                fecha_creacion)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            plan.get("url_portal", ""),
            campo.get("campo_origen", ""),
            campo.get("campo_destino", ""),
            p, p, now,
        ))

    conn.commit()
    conn.close()
    return plan_id


def cargar_plan_activo(url_portal: str) -> dict | None:
    """Carga el plan activo para un portal. None si no existe."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT plan_json FROM planes WHERE url_portal=? AND activo=1 ORDER BY id DESC LIMIT 1",
        (url_portal,)
    )
    row = cur.fetchone()
    conn.close()
    return json.loads(row["plan_json"]) if row else None


def actualizar_confianza_mapeo(url_portal: str, campo_origen: str,
                                confirmado: bool):
    """
    Actualiza la confianza bayesiana de un mapeo.
    Confirmado=True sube la confianza, False la baja.
    """
    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()

    cur.execute("""
        SELECT id, confianza_actual, n_confirmaciones, n_correcciones
        FROM mapeos WHERE url_portal=? AND campo_origen=?
        ORDER BY id DESC LIMIT 1
    """, (url_portal, campo_origen))

    row = cur.fetchone()
    if row:
        p     = row["confianza_actual"]
        n_c   = row["n_confirmaciones"]
        n_err = row["n_correcciones"]

        # Actualización bayesiana simple
        if confirmado:
            nueva_p = min(0.99, p + (1 - p) * 0.1)
            n_c += 1
        else:
            nueva_p = max(0.01, p - p * 0.15)
            n_err += 1

        cur.execute("""
            UPDATE mapeos SET confianza_actual=?, n_confirmaciones=?,
                              n_correcciones=?, fecha_actualizacion=?
            WHERE id=?
        """, (nueva_p, n_c, n_err, now, row["id"]))

    conn.commit()
    conn.close()


# ─── Sesiones ─────────────────────────────────────────────────────────────────

def guardar_sesion(plan: dict, resultados: list, email: str,
                   duracion_seg: float = None, plan_id: int = None) -> int:
    """Guarda el resultado de una ejecución. Devuelve el ID de sesión."""
    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()

    ok   = sum(1 for r in resultados if r.get("estado") == "ok")
    err  = sum(1 for r in resultados if r.get("estado") == "error")
    warn = sum(1 for r in resultados if r.get("estado") == "advertencia")

    cur.execute("""
        INSERT INTO sesiones (fecha, email_usuario, url_portal,
                              plataforma_origen, plataforma_destino,
                              n_pasos, n_exitosos, n_errores, n_advertencias,
                              duracion_seg, plan_id, resultado_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now, email,
        plan.get("url_portal", ""),
        plan.get("plataforma_origen", ""),
        plan.get("plataforma_destino", ""),
        len(resultados), ok, err, warn,
        duracion_seg, plan_id,
        json.dumps(resultados, ensure_ascii=False),
    ))

    sesion_id = cur.lastrowid

    # Guardar errores individuales
    for r in resultados:
        if r.get("estado") != "ok":
            cur.execute("""
                INSERT INTO errores (sesion_id, paso, accion, descripcion, fecha)
                VALUES (?, ?, ?, ?, ?)
            """, (
                sesion_id,
                r.get("paso"),
                r.get("accion", ""),
                str(r.get("datos_extraidos", "")),
                now,
            ))

    conn.commit()
    conn.close()
    return sesion_id


def obtener_historial(limit: int = 20) -> list:
    """Devuelve las últimas N sesiones para el dashboard."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, fecha, email_usuario, url_portal,
               plataforma_origen, plataforma_destino,
               n_pasos, n_exitosos, n_errores, duracion_seg
        FROM sesiones
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def obtener_estadisticas() -> dict:
    """Estadísticas globales para el dashboard ejecutivo."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) as total FROM sesiones")
    total = cur.fetchone()["total"]

    cur.execute("SELECT AVG(CAST(n_exitosos AS REAL)/NULLIF(n_pasos,0))*100 as tasa FROM sesiones")
    tasa = cur.fetchone()["tasa"] or 0

    cur.execute("SELECT COUNT(*) as total FROM planes WHERE activo=1")
    n_planes = cur.fetchone()["total"]

    cur.execute("""
        SELECT plataforma_origen, COUNT(*) as n
        FROM sesiones GROUP BY plataforma_origen
        ORDER BY n DESC LIMIT 5
    """)
    top_portales = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "total_sesiones": total,
        "tasa_exito_pct": round(tasa, 1),
        "planes_activos": n_planes,
        "top_portales":   top_portales,
    }


# ─── Init automático al importar ──────────────────────────────────────────────
init_db()
