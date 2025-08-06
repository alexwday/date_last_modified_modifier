#!/usr/bin/env python3
"""
Comprehensive logging configuration with multiple handlers and formatters.
Provides structured logging with file rotation, console output, and error tracking.
"""

import os
import sys
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
import json
import traceback
from typing import Optional, Dict, Any


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured logs in JSON format."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage(),
            'thread': record.thread,
            'thread_name': record.threadName,
            'process': record.process,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName', 'relativeCreated',
                          'stack_info', 'thread', 'threadName', 'exc_info', 'exc_text']:
                log_data[key] = value
        
        return json.dumps(log_data)


class ColoredConsoleFormatter(logging.Formatter):
    """Colored formatter for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class LogManager:
    """Centralized log management with multiple handlers and configurations."""
    
    def __init__(self, app_name: str = "pdf_date_modifier", log_dir: Optional[Path] = None):
        self.app_name = app_name
        self.log_dir = log_dir or Path.home() / '.pdf_date_modifier' / 'logs'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.loggers: Dict[str, logging.Logger] = {}
        self.handlers: Dict[str, logging.Handler] = {}
        
        # Create default handlers
        self._setup_handlers()
        
    def _setup_handlers(self):
        """Setup default logging handlers."""
        
        # Console handler with colored output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = ColoredConsoleFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.handlers['console'] = console_handler
        
        # Main application log file (rotating)
        app_log_file = self.log_dir / f"{self.app_name}.log"
        app_file_handler = logging.handlers.RotatingFileHandler(
            app_log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        app_file_handler.setLevel(logging.DEBUG)
        app_file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        app_file_handler.setFormatter(app_file_formatter)
        self.handlers['app_file'] = app_file_handler
        
        # Error log file (only errors and above)
        error_log_file = self.log_dir / f"{self.app_name}_errors.log"
        error_file_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(app_file_formatter)
        self.handlers['error_file'] = error_file_handler
        
        # Structured JSON log file for analysis
        json_log_file = self.log_dir / f"{self.app_name}_structured.jsonl"
        json_file_handler = logging.handlers.RotatingFileHandler(
            json_log_file,
            maxBytes=20 * 1024 * 1024,  # 20MB
            backupCount=3,
            encoding='utf-8'
        )
        json_file_handler.setLevel(logging.DEBUG)
        json_formatter = StructuredFormatter()
        json_file_handler.setFormatter(json_formatter)
        self.handlers['json_file'] = json_file_handler
        
    def get_logger(self, name: str, level: int = logging.DEBUG) -> logging.Logger:
        """Get or create a logger with the specified name."""
        
        if name in self.loggers:
            return self.loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        
        # Add all handlers
        for handler in self.handlers.values():
            logger.addHandler(handler)
        
        self.loggers[name] = logger
        return logger
    
    def set_console_level(self, level: int):
        """Adjust console logging level."""
        self.handlers['console'].setLevel(level)
    
    def add_custom_handler(self, name: str, handler: logging.Handler):
        """Add a custom handler to all loggers."""
        self.handlers[name] = handler
        for logger in self.loggers.values():
            logger.addHandler(handler)
    
    def get_log_files(self) -> Dict[str, Path]:
        """Get paths to all log files."""
        return {
            'application': self.log_dir / f"{self.app_name}.log",
            'errors': self.log_dir / f"{self.app_name}_errors.log",
            'structured': self.log_dir / f"{self.app_name}_structured.jsonl",
        }
    
    def clean_old_logs(self, days: int = 30):
        """Clean up log files older than specified days."""
        import time
        
        current_time = time.time()
        for log_file in self.log_dir.glob("*.log*"):
            if log_file.stat().st_mtime < current_time - (days * 86400):
                try:
                    log_file.unlink()
                except Exception:
                    pass


class LogContext:
    """Context manager for adding context to log messages."""
    
    def __init__(self, logger: logging.Logger, **context):
        self.logger = logger
        self.context = context
        self.old_context = {}
        
    def __enter__(self):
        for key, value in self.context.items():
            if hasattr(self.logger, key):
                self.old_context[key] = getattr(self.logger, key)
            setattr(self.logger, key, value)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        for key in self.context:
            if key in self.old_context:
                setattr(self.logger, key, self.old_context[key])
            else:
                delattr(self.logger, key)


# Global log manager instance
_log_manager: Optional[LogManager] = None


def initialize_logging(app_name: str = "pdf_date_modifier", 
                       log_dir: Optional[Path] = None,
                       console_level: int = logging.INFO) -> LogManager:
    """Initialize global logging configuration."""
    global _log_manager
    
    if _log_manager is None:
        _log_manager = LogManager(app_name, log_dir)
        _log_manager.set_console_level(console_level)
        
        # Log initialization
        logger = _log_manager.get_logger('core.logging')
        logger.info(f"Logging initialized for {app_name}")
        logger.info(f"Log directory: {_log_manager.log_dir}")
        
    return _log_manager


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    global _log_manager
    
    if _log_manager is None:
        _log_manager = initialize_logging()
    
    return _log_manager.get_logger(name)


def log_exception(logger: logging.Logger, exc: Exception, context: Optional[Dict[str, Any]] = None):
    """Log an exception with full context."""
    exc_info = {
        'exception_type': type(exc).__name__,
        'exception_message': str(exc),
        'traceback': traceback.format_exc(),
    }
    
    if context:
        exc_info.update(context)
    
    logger.error(f"Exception occurred: {exc}", exc_info=True, extra=exc_info)


def performance_logger(func):
    """Decorator to log function performance."""
    import functools
    import time
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__name__} completed in {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.3f}s: {e}")
            raise
    
    return wrapper