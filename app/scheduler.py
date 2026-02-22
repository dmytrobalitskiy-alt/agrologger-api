from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import psycopg2

# Конфіг БД (можна винести у config.py)
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


def aggregate_daily_weather():
    conn = get_conn()
    cur = conn.cursor()

    # Вибираємо всі поля
    cur.execute("SELECT id FROM fields")
    fields = cur.fetchall()

    for (field_id,) in fields:
        cur.execute("""
            SELECT temp, humidity, pressure, battery, signal, timestamp
            FROM weather_hourly
            WHERE field_id = %s AND timestamp::date = %s
            ORDER BY timestamp DESC
        """, (field_id, datetime.now().date()))

        rows = cur.fetchall()
        if not rows:
            continue

        temps = [r[0] for r in rows if r[0] is not None]
        hums = [r[1] for r in rows if r[1] is not None]
        press = [r[2] for r in rows if r[2] is not None]

        battery_last = rows[0][3]
        signal_last = rows[0][4]

        temp_min = min(temps)
        temp_max = max(temps)
        temp_avg = sum(temps) / len(temps)
        hum_avg = sum(hums) / len(hums)
        press_avg = sum(press) / len(press)

        cur.execute("""
            INSERT INTO weather_daily (field_id, date, temp_min, temp_max, temp_avg, humidity_avg, pressure_avg, battery, signal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (field_id, date) DO NOTHING
        """, (field_id, datetime.now().date(), temp_min, temp_max, temp_avg, hum_avg, press_avg, battery_last, signal_last))

    conn.commit()
    cur.close()
    conn.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(aggregate_daily_weather, 'cron', hour=23, minute=59)
    scheduler.start()
