import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import config

DATA_DIR = Path(os.environ.get('EXAM_DATA_DIR', config.project_root / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
db_path = DATA_DIR / 'db/events.db'
db_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f'sqlite:///{db_path.as_posix()}', connect_args={'check_same_thread': False, 'timeout': 30})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    time_str = Column(String)
    student_id = Column(Integer, index=True)
    seat_id = Column(Integer)
    event_type = Column(String, index=True)
    confidence = Column(Float)
    risk_level = Column(String)
    risk_score = Column(Float)
    duration = Column(Float)
    reasoning = Column(Text)
    evidence_frame_path = Column(String)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    state = Column(String)
    session_id = Column(String, index=True)
    is_demo = Column(Boolean, default=False)
    video_time = Column(Float, default=0)


def initialize_database():
    Base.metadata.create_all(engine)
    columns = {column['name'] for column in inspect(engine).get_columns('events')}
    with engine.begin() as connection:
        for name, sql_type in [('session_id', 'VARCHAR'), ('is_demo', 'BOOLEAN DEFAULT 0'), ('video_time', 'FLOAT DEFAULT 0')]:
            if name not in columns:
                connection.execute(text(f'ALTER TABLE events ADD COLUMN {name} {sql_type}'))
        connection.execute(text('PRAGMA journal_mode=WAL'))


def get_db():
    with SessionLocal() as database:
        yield database
