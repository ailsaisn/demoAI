import sys
import os
import logging
from collections import deque
from typing import List, Optional
from loguru import logger

# Thread-safe in-memory ring buffer for recent log lines (last 3,000 entries)
LOG_MEMORY_BUFFER = deque(maxlen=3000)

def _memory_log_sink(message):
    LOG_MEMORY_BUFFER.append(str(message).strip())

class InterceptHandler(logging.Handler):
    """
    Redirect standard logging (Uvicorn, FastAPI, SQLAlchemy, HTTPX) to Loguru.
    """
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logging(log_level: str = "INFO"):
    """
    Configures standard logging across the entire application:
    1. Intercepts standard Python logging (Uvicorn, SQLAlchemy, HTTPX, asyncio).
    2. Outputs formatted logs to stdout.
    3. Persists full debug logs to logs/app.log (rotating 10MB, 10 days).
    4. Records last 3,000 entries in in-memory buffer for real-time API queries.
    """
    logger.remove() # Remove default handler
    
    # 1. Stdout handler (Clean colorized formatting)
    logger.add(
        sys.stdout, 
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 2. File handler (Full debug persistence)
    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/app.log", 
        level="DEBUG",
        rotation="10 MB",
        retention="10 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )

    # 3. In-memory buffer sink for web API query
    logger.add(
        _memory_log_sink,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )

    # 4. Intercept standard library loggers
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "sqlalchemy.engine", "httpx", "urllib3"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False
    
    logger.info("Universal logging configured successfully (stdout + file + memory buffer).")

def get_recent_logs(lines: int = 300, level: Optional[str] = None, search: Optional[str] = None) -> List[str]:
    """Retrieve recent log lines from memory buffer or logs/app.log."""
    raw_logs = list(LOG_MEMORY_BUFFER)
    
    # Fallback to reading logs/app.log if buffer is empty
    if not raw_logs and os.path.exists("logs/app.log"):
        try:
            with open("logs/app.log", "r", encoding="utf-8", errors="ignore") as f:
                raw_logs = [line.strip() for line in f.readlines() if line.strip()]
        except Exception:
            pass
            
    filtered = raw_logs
    if level:
        lvl_upper = level.upper()
        filtered = [l for l in filtered if f"| {lvl_upper}" in l or f"[{lvl_upper}]" in l]
        
    if search:
        s_lower = search.lower()
        filtered = [l for l in filtered if s_lower in l.lower()]
        
    return filtered[-lines:]

