from pydantic import BaseModel
from datetime import datetime

class HourlyWeatherData(BaseModel):
    logger_id: int
    timestamp: datetime
    temp: float
    humidity: float
    pressure: float
    battery: float
    signal: float
