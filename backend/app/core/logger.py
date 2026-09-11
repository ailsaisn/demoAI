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
        # Ignore noisy periodic 200 OK health check logs and Hugging Face cache HEAD/GET checks
        message = record.getMessage()
        if ("GET /health" in message and " 200" in message) or any(k in message for k in ["huggingface.co", "resolve-cache", "additional_chat_templates"]):
            return

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, message)

def _can_write_and_rotate_log(log_dir: str = "logs") -> bool:
    """
    Checks if the application has full POSIX permissions to write and rotate files in log_dir.
    Returns True if log rotation is safe, False if file logging should be skipped to prevent PermissionError.
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
        test_path = os.path.join(log_dir, ".perm_test.tmp")
        renamed_path = os.path.join(log_dir, ".perm_test_renamed.tmp")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("test")
        os.rename(test_path, renamed_path)
        os.remove(renamed_path)
        return True
    except Exception:
        return False

def setup_logging(log_level: str = "INFO"):
    """
    Configures standard logging across the entire application:
    1. Intercepts standard Python logging (Uvicorn, SQLAlchemy, HTTPX, asyncio).
    2. Outputs formatted logs to stdout.
    3. Persists full debug logs to logs/app.log (rotating 10MB, 10 days) if directory permissions allow.
    4. Records last 3,000 entries in in-memory buffer for real-time API queries.
    """
    logger.remove() # Remove default handler
    
    # 1. Stdout handler (Clean colorized formatting)
    logger.add(
        sys.stdout, 
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 2. File handler (Full debug persistence, multiprocess safe with enqueue=True and permission guard)
    if _can_write_and_rotate_log("logs"):
        try:
            logger.add(
                "logs/app.log", 
                level="DEBUG",
                rotation="10 MB",
                retention="10 days",
                enqueue=True,
                catch=True,
                encoding="utf-8",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
            )
        except Exception as err:
            sys.stderr.write(f"Warning: Could not initialize file logger 'logs/app.log': {err}\n")
    else:
        sys.stderr.write("Notice: Directory 'logs' lacks file rotation permissions in this container/OS environment. File logging disabled safely (app running via stdout + memory buffer).\n")

    # 3. In-memory buffer sink for web API query
    logger.add(
        _memory_log_sink,
        level="DEBUG",
        enqueue=True,
        catch=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )

    # 4. Intercept standard library loggers
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "sqlalchemy.engine", "httpx", "urllib3", "huggingface_hub", "transformers", "sentence_transformers"):
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

