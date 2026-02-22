from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import psycopg2
import os
from urllib.parse import urlparse

from app.routers import iot
from app.scheduler import start_scheduler

# ---------- APP ----------
app = FastAPI(title="AgroLogger API")

# підключаємо IoT router
app.include_router(iot.router)

# ---------- DB CONFIG ----------
DATABASE_URL = os.getenv("DATABASE_URL") 

def get_conn():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set in environment")

    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=result.hostname,
        database=result.path[1:], # прибираємо "/" на початку
        user=result.username,
        password=result.password,
        port=result.port
    )


# ---------- MODELS ----------
class GDDItem(BaseModel):
    field_id: int
    date: str
    gdd: float
    gdd_sum: float


class TempDailyItem(BaseModel):
    field_id: int
    date: str
    temp_min: float
    temp_max: float
    temp_avg: float


class PhaseItem(BaseModel):
    phase_name: str
    gdd_from: float
    gdd_to: float
    current_gdd: float
    is_active: bool
    gdd_left: float


class PhaseCreateItem(BaseModel):
    hybrid_id: int
    phase_name: str
    gdd_from: float
    gdd_to: float


# ---------- MODELS DASHBOARD ----------
class FieldInfo(BaseModel):
    id: int
    name: str
    hybrid: str


class CurrentStatus(BaseModel):
    gdd: float
    temp_avg: float


class PhaseDashboardItem(BaseModel):
    phase_name: str
    gdd_from: float
    gdd_to: float
    current_gdd: float
    is_active: bool
    gdd_left: float
    completed: bool


class LiveStatus(BaseModel):
    battery: float
    signal: float
    pressure: float
    temperature: float
    timestamp: str


class DashboardResponse(BaseModel):
    field: FieldInfo
    current: CurrentStatus
    phases: List[PhaseDashboardItem]
    live: Optional[LiveStatus]


# ---------- ENDPOINTS ----------

# GDD
@app.get("/gdd/{field_id}", response_model=List[GDDItem])
def get_gdd(field_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT field_id, date, gdd, gdd_sum
            FROM v_gdd_cumulative_v2
            WHERE field_id = %s
            ORDER BY date
        """, (field_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            GDDItem(
                field_id=r[0],
                date=str(r[1]),
                gdd=float(r[2]),
                gdd_sum=float(r[3])
            ) for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# TEMPERATURE
@app.get("/temperature/{field_id}", response_model=List[TempDailyItem])
def get_temperature(field_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT field_id, date, temp_min, temp_max, temp_avg
            FROM v_weather_daily_calc
            WHERE field_id = %s
            ORDER BY date
        """, (field_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            TempDailyItem(
                field_id=r[0],
                date=str(r[1]),
                temp_min=float(r[2]),
                temp_max=float(r[3]),
                temp_avg=float(r[4])
            ) for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# PHASES
@app.get("/phase/{field_id}", response_model=List[PhaseItem])
def get_phases(field_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Отримуємо hybrid_id
        cur.execute("SELECT hybrid_id FROM fields WHERE id = %s", (field_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Field not found")
        hybrid_id = row[0]

        # Поточний сумарний GDD
        cur.execute("""
            SELECT gdd_sum
            FROM v_gdd_cumulative_v2
            WHERE field_id = %s
            ORDER BY date DESC
            LIMIT 1
        """, (field_id,))
        gdd_row = cur.fetchone()
        current_gdd = float(gdd_row[0]) if gdd_row else 0.0

        # Беремо всі фази для гібриду
        cur.execute("""
            SELECT phase_name, gdd_from, gdd_to
            FROM phases
            WHERE hybrid_id = %s
            ORDER BY gdd_from
        """, (hybrid_id,))
        phases = cur.fetchall()

        cur.close()
        conn.close()

        result = []
        for p in phases:
            gdd_from = float(p[1])
            gdd_to = float(p[2])
            is_active = gdd_from <= current_gdd <= gdd_to
            gdd_left = max(0.0, gdd_to - current_gdd) if is_active else 0.0

            result.append(
                PhaseItem(
                    phase_name=p[0],
                    gdd_from=gdd_from,
                    gdd_to=gdd_to,
                    current_gdd=current_gdd,
                    is_active=is_active,
                    gdd_left=gdd_left
                )
            )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# CREATE PHASE
@app.post("/phase/", response_model=PhaseItem)
def create_phase(phase: PhaseCreateItem):
    try:
        conn = get_conn()
        cur = conn.cursor()

        # обмеження 10 фаз
        cur.execute("SELECT COUNT(*) FROM phases WHERE hybrid_id = %s", (phase.hybrid_id,))
        if cur.fetchone()[0] >= 10:
            raise HTTPException(status_code=400, detail="Максимум 10 фаз на гібрид")

        cur.execute("""
            INSERT INTO phases (hybrid_id, phase_name, gdd_from, gdd_to)
            VALUES (%s, %s, %s, %s)
            RETURNING phase_name, gdd_from, gdd_to
        """, (phase.hybrid_id, phase.phase_name, phase.gdd_from, phase.gdd_to))

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return PhaseItem(
            phase_name=row[0],
            gdd_from=float(row[1]),
            gdd_to=float(row[2]),
            current_gdd=0.0,
            is_active=False,
            gdd_left=0.0
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# DASHBOARD
@app.get("/dashboard/{field_id}", response_model=DashboardResponse)
def get_dashboard(field_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Інформація про поле
        cur.execute("""
            SELECT f.id, f.name, h.name, f.logger_id
            FROM fields f
            JOIN hybrids h ON f.hybrid_id = h.id
            WHERE f.id = %s
        """, (field_id,))
        field_res = cur.fetchone()
        if not field_res:
            raise HTTPException(status_code=404, detail="Field not found")
        field_info = FieldInfo(id=field_res[0], name=field_res[1], hybrid=field_res[2])
        logger_id = field_res[3]

        # Поточний GDD
        cur.execute("""
            SELECT gdd_sum
            FROM v_gdd_cumulative_v2
            WHERE field_id = %s
            ORDER BY date DESC
            LIMIT 1
        """, (field_id,))
        gdd_res = cur.fetchone()
        current_gdd = float(gdd_res[0]) if gdd_res else 0.0

        # Поточна середня температура
        cur.execute("""
            SELECT temp_avg
            FROM v_weather_daily_calc
            WHERE field_id = %s
            ORDER BY date DESC
            LIMIT 1
        """, (field_id,))
        temp_res = cur.fetchone()
        temp_avg = float(temp_res[0]) if temp_res else 0.0
        current_status = CurrentStatus(gdd=current_gdd, temp_avg=temp_avg)

        # Фази
        cur.execute("""
            SELECT phase_name, gdd_from, gdd_to
            FROM phases
            WHERE hybrid_id = (SELECT hybrid_id FROM fields WHERE id = %s)
            ORDER BY gdd_from
        """, (field_id,))
        rows = cur.fetchall()

        phases_list = []
        for r in rows:
            gdd_from = float(r[1])
            gdd_to = float(r[2])
            is_active = gdd_from <= current_gdd <= gdd_to
            completed = current_gdd > gdd_to
            gdd_left = max(0.0, gdd_to - current_gdd) if is_active else 0.0

            phases_list.append(
                PhaseDashboardItem(
                    phase_name=r[0],
                    gdd_from=gdd_from,
                    gdd_to=gdd_to,
                    current_gdd=current_gdd,
                    is_active=is_active,
                    gdd_left=gdd_left,
                    completed=completed
                )
            )

        # Live status (останній запис з weather_hourly)
        cur.execute("""
            SELECT battery, signal, pressure, temp, timestamp
            FROM weather_hourly
            WHERE logger_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (logger_id,))
        live_row = cur.fetchone()
        live_status = None
        if live_row:
            live_status = LiveStatus(
                battery=float(live_row[0]),
                signal=float(live_row[1]),
                pressure=float(live_row[2]),
                temperature=float(live_row[3]),
                timestamp=str(live_row[4])
            )

        cur.close()
        conn.close()

        return DashboardResponse(
            field=field_info,
            current=current_status,
            phases=phases_list,
            live=live_status
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
