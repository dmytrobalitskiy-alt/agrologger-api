from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import time
import logging   # ⬅️ додаємо логування

router = APIRouter(prefix="/iot", tags=["IoT"])

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


# ---------- SECURITY ----------
API_KEY = "supersecretkey123"  # тимчасово, потім винесемо у .env

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

# ---------- RATE LIMITING ----------
last_request_time = {}
RATE_LIMIT_SECONDS = 60

# ---------- LOGGING ----------
logging.basicConfig(
    filename="iot_requests.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------- SCHEMA ----------
class HourlyWeatherData(BaseModel):
    logger_id: int
    serial_number: str
    timestamp: datetime
    temp: float
    humidity: float
    pressure: float
    battery: float
    signal: float


# ---------- ENDPOINT ----------
@router.post("/weather")
def ingest_weather(
    data: HourlyWeatherData,
    api_key: str = Depends(verify_api_key)
):

    conn = None
    cur = None

    try:
        # 0️⃣ Rate limiting
        now = time.time()
        last_time = last_request_time.get(data.logger_id)
        if last_time and (now - last_time < RATE_LIMIT_SECONDS):
            logging.warning(f"Rate limit exceeded for logger_id={data.logger_id}")
            raise HTTPException(status_code=429, detail="Too many requests")
        last_request_time[data.logger_id] = now

        conn = get_conn()
        cur = conn.cursor()

        # 1️⃣ Перевірка логера і serial_number
        cur.execute("SELECT serial_number FROM loggers WHERE id = %s", (data.logger_id,))
        logger = cur.fetchone()

        if not logger:
            logging.error(f"Logger not found: logger_id={data.logger_id}")
            raise HTTPException(status_code=404, detail="Logger not found")

        db_serial = logger[0]
        if db_serial != data.serial_number:
            logging.error(f"Invalid serial number for logger_id={data.logger_id}")
            raise HTTPException(status_code=401, detail="Invalid serial number")

        # 2️⃣ Знайти всі поля для цього логера
        cur.execute("SELECT id FROM fields WHERE logger_id = %s", (data.logger_id,))
        fields = cur.fetchall()

        if not fields:
            logging.error(f"No fields found for logger_id={data.logger_id}")
            raise HTTPException(status_code=404, detail="No fields found for this logger")

        # 3️⃣ Записати дані
        for field in fields:
            field_id = field[0]

            cur.execute("""
                SELECT id FROM weather_hourly
                WHERE logger_id = %s
                AND field_id = %s
                AND timestamp = %s
            """, (data.logger_id, field_id, data.timestamp))

            exists = cur.fetchone()

            if not exists:
                cur.execute("""
                    INSERT INTO weather_hourly (
                        logger_id, field_id, timestamp,
                        temp, humidity, pressure, battery, signal
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data.logger_id,
                    field_id,
                    data.timestamp,
                    data.temp,
                    data.humidity,
                    data.pressure,
                    data.battery,
                    data.signal
                ))

        conn.commit()
        logging.info(
            f"Weather data saved: logger_id={data.logger_id}, serial={data.serial_number}, "
            f"timestamp={data.timestamp}, temp={data.temp}, humidity={data.humidity}, "
            f"pressure={data.pressure}, battery={data.battery}, signal={data.signal}"
        )
        return {"status": "ok"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Error ingesting weather data for logger_id={data.logger_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
