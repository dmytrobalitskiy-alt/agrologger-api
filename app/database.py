from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql://postgres:password@localhost:5432/agrologger"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# 👇 ОЦЕ ОБОВ’ЯЗКОВО
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
