from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config.config import Config
from src.adapters.logger import logger

DATABASE_URL = (
    f"mysql+pymysql://{Config.MYSQL_USER}:{Config.MYSQL_PASSWORD}"
    f"@{Config.MYSQL_HOST}:{Config.MYSQL_PORT}/{Config.MYSQL_DATABASE}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def init_db() -> None:
    """
    Creates required tables if they don't already exist. Called once at
    application startup.
    """
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
    """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sessions (
                id VARCHAR(36) PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
    """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
    """))
        
        conn.commit()
    logger.info('STATUS: MySQL tables initizalized successfully')

def get_db_sessions():
    """FastAPI dependency — yields a DB session and ensures it's closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()        