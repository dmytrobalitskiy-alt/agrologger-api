from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class WeatherIngest(BaseModel):
    logger_id: int
    timestamp: datetime
    temperature: float
    humidity: Optional[float] = None
    pressure: Optional[float] = None
