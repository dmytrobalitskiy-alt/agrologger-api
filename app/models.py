from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class WeatherHourly(Base):
    __tablename__ = "weather_hourly"

    id = Column(Integer, primary_key=True, index=True)
    logger_id = Column(Integer, ForeignKey("loggers.id"))
    field_id = Column(Integer, ForeignKey("fields.id"))
    timestamp = Column(DateTime, nullable=False)

    temp = Column(Float)
    humidity = Column(Float)
    pressure = Column(Float)
    battery = Column(Float)
    signal = Column(Float)
