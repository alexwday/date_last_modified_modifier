#!/usr/bin/env python3
"""
Configuration management with validation, persistence, and environment support.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field
from datetime import datetime
import configparser
from cryptography.fernet import Fernet
import base64
import hashlib

from .logging_config import get_logger


@dataclass
class ServerConfig:
    """Server connection configuration."""
    nas_ip: str = ""
    username: str = ""
    password: str = ""
    share_name: str = ""
    base_path: str = "/"
    folder_path: str = ""  # Optional folder path to append to base_path
    domain: str = ""
    port: int = 445
    timeout: int = 30
    use_ntlm_v2: bool = True
    is_direct_tcp: bool = True


@dataclass
class ApplicationConfig:
    """Application-wide configuration."""
    # Logging
    log_level: str = "INFO"
    log_dir: Optional[str] = None
    log_retention_days: int = 30
    
    # Performance
    max_worker_threads: int = 5
    connection_pool_size: int = 3
    task_timeout: int = 300
    retry_max_attempts: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    
    # File operations
    backup_enabled: bool = True
    backup_dir: Optional[str] = None
    backup_retention_hours: int = 24
    verify_checksums: bool = True
    atomic_operations: bool = True
    
    # UI preferences
    window_width: int = 1400
    window_height: int = 900
    theme: str = "Fusion"
    show_tooltips: bool = True
    auto_advance: bool = True
    auto_advance_delay: int = 1500
    
    # PDF processing
    update_pdf_metadata: bool = True
    repair_corrupted_pdfs: bool = True
    validate_pdfs: bool = True
    
    # Network
    keepalive_interval: int = 60
    max_idle_time: int = 300
    connection_health_check: bool = True


@dataclass
class Configuration:
    """Complete application configuration."""
    server: ServerConfig = field(default_factory=ServerConfig)
    app: ApplicationConfig = field(default_factory=ApplicationConfig)
    recent_connections: List[Dict[str, str]] = field(default_factory=list)
    saved_searches: List[str] = field(default_factory=list)


class ConfigValidator:
    """Validate configuration values."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_server_config(self, config: ServerConfig) -> bool:
        """Validate server configuration."""
        
        self.errors.clear()
        self.warnings.clear()
        
        # Validate IP address
        if config.nas_ip:
            import ipaddress
            try:
                ipaddress.ip_address(config.nas_ip)
            except ValueError:
                # Try as hostname
                import socket
                try:
                    socket.gethostbyname(config.nas_ip)
                except socket.error:
                    self.errors.append(f"Invalid IP address or hostname: {config.nas_ip}")
        
        # Validate port
        if not 1 <= config.port <= 65535:
            self.errors.append(f"Invalid port number: {config.port}")
        
        # Validate timeout
        if config.timeout < 1:
            self.warnings.append(f"Very low timeout value: {config.timeout}")
        
        # Validate paths
        if config.base_path and not config.base_path.startswith('/'):
            self.warnings.append(f"Base path should start with '/': {config.base_path}")
        
        return len(self.errors) == 0
    
    def validate_app_config(self, config: ApplicationConfig) -> bool:
        """Validate application configuration."""
        
        self.errors.clear()
        self.warnings.clear()
        
        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if config.log_level.upper() not in valid_levels:
            self.errors.append(f"Invalid log level: {config.log_level}")
        
        # Validate thread counts
        if config.max_worker_threads < 1:
            self.errors.append("max_worker_threads must be at least 1")
        elif config.max_worker_threads > 20:
            self.warnings.append(f"High worker thread count: {config.max_worker_threads}")
        
        if config.connection_pool_size < 1:
            self.errors.append("connection_pool_size must be at least 1")
        
        # Validate timeouts
        if config.task_timeout < 1:
            self.errors.append("task_timeout must be positive")
        
        # Validate UI dimensions
        if config.window_width < 800 or config.window_height < 600:
            self.warnings.append("Window size may be too small")
        
        return len(self.errors) == 0
    
    def get_validation_report(self) -> Dict[str, List[str]]:
        """Get validation errors and warnings."""
        return {
            'errors': self.errors.copy(),
            'warnings': self.warnings.copy()
        }


class SecureStorage:
    """Secure storage for sensitive configuration data."""
    
    def __init__(self, key_file: Optional[Path] = None):
        self.logger = get_logger(__name__)
        self.key_file = key_file or Path.home() / '.pdf_date_modifier' / '.key'
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = self._get_or_create_cipher()
    
    def _get_or_create_cipher(self) -> Fernet:
        """Get existing or create new encryption key."""
        
        if self.key_file.exists():
            try:
                with open(self.key_file, 'rb') as f:
                    key = f.read()
                return Fernet(key)
            except Exception as e:
                self.logger.warning(f"Failed to load encryption key: {e}")
        
        # Generate new key
        key = Fernet.generate_key()
        
        try:
            with open(self.key_file, 'wb') as f:
                f.write(key)
            
            # Set restrictive permissions on Unix-like systems
            if os.name != 'nt':
                os.chmod(self.key_file, 0o600)
                
        except Exception as e:
            self.logger.error(f"Failed to save encryption key: {e}")
        
        return Fernet(key)
    
    def encrypt(self, data: str) -> str:
        """Encrypt sensitive data."""
        try:
            encrypted = self.cipher.encrypt(data.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            self.logger.error(f"Encryption failed: {e}")
            return data
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt sensitive data."""
        try:
            decoded = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted = self.cipher.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            self.logger.error(f"Decryption failed: {e}")
            return encrypted_data


class ConfigurationManager:
    """Main configuration management class."""
    
    def __init__(self, config_file: Optional[Path] = None):
        self.logger = get_logger(__name__)
        self.config_file = config_file or Path.home() / '.pdf_date_modifier' / 'config.json'
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.config = Configuration()
        self.validator = ConfigValidator()
        self.secure_storage = SecureStorage()
        
        # Load configuration
        self.load()
        
        # Apply environment overrides
        self._apply_env_overrides()
    
    def load(self) -> bool:
        """Load configuration from file."""
        
        if not self.config_file.exists():
            self.logger.info("No configuration file found, using defaults")
            return False
        
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            
            # Load server config
            if 'server' in data:
                server_data = data['server']
                
                # Decrypt password if present
                if 'password' in server_data and server_data['password']:
                    server_data['password'] = self.secure_storage.decrypt(server_data['password'])
                
                self.config.server = ServerConfig(**server_data)
            
            # Load app config
            if 'app' in data:
                self.config.app = ApplicationConfig(**data['app'])
            
            # Load recent connections
            if 'recent_connections' in data:
                self.config.recent_connections = data['recent_connections']
                
                # Decrypt passwords
                for conn in self.config.recent_connections:
                    if 'password' in conn and conn['password']:
                        conn['password'] = self.secure_storage.decrypt(conn['password'])
            
            # Load saved searches
            if 'saved_searches' in data:
                self.config.saved_searches = data['saved_searches']
            
            self.logger.info(f"Configuration loaded from {self.config_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return False
    
    def save(self) -> bool:
        """Save configuration to file."""
        
        try:
            # Prepare data for saving
            data = {
                'server': asdict(self.config.server),
                'app': asdict(self.config.app),
                'recent_connections': self.config.recent_connections.copy(),
                'saved_searches': self.config.saved_searches.copy()
            }
            
            # Encrypt sensitive data
            if data['server']['password']:
                data['server']['password'] = self.secure_storage.encrypt(data['server']['password'])
            
            for conn in data['recent_connections']:
                if 'password' in conn and conn['password']:
                    conn['password'] = self.secure_storage.encrypt(conn['password'])
            
            # Write to file
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Set restrictive permissions on Unix-like systems
            if os.name != 'nt':
                os.chmod(self.config_file, 0o600)
            
            self.logger.info(f"Configuration saved to {self.config_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save configuration: {e}")
            return False
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides."""
        
        # Server overrides
        if nas_ip := os.getenv('PDF_MOD_NAS_IP'):
            self.config.server.nas_ip = nas_ip
        
        if username := os.getenv('PDF_MOD_USERNAME'):
            self.config.server.username = username
        
        if password := os.getenv('PDF_MOD_PASSWORD'):
            self.config.server.password = password
        
        if share := os.getenv('PDF_MOD_SHARE'):
            self.config.server.share_name = share
        
        # App overrides
        if log_level := os.getenv('PDF_MOD_LOG_LEVEL'):
            self.config.app.log_level = log_level
        
        if workers := os.getenv('PDF_MOD_MAX_WORKERS'):
            try:
                self.config.app.max_worker_threads = int(workers)
            except ValueError:
                self.logger.warning(f"Invalid PDF_MOD_MAX_WORKERS value: {workers}")
    
    def validate(self) -> bool:
        """Validate current configuration."""
        
        server_valid = self.validator.validate_server_config(self.config.server)
        app_valid = self.validator.validate_app_config(self.config.app)
        
        report = self.validator.get_validation_report()
        
        if report['errors']:
            for error in report['errors']:
                self.logger.error(f"Configuration error: {error}")
        
        if report['warnings']:
            for warning in report['warnings']:
                self.logger.warning(f"Configuration warning: {warning}")
        
        return server_valid and app_valid
    
    def add_recent_connection(self, server_config: ServerConfig):
        """Add a connection to recent connections list."""
        
        connection = {
            'nas_ip': server_config.nas_ip,
            'username': server_config.username,
            'password': server_config.password,
            'share_name': server_config.share_name,
            'base_path': server_config.base_path,
            'folder_path': server_config.folder_path if hasattr(server_config, 'folder_path') else "",
            'timestamp': datetime.now().isoformat()
        }
        
        # Remove duplicates
        self.config.recent_connections = [
            c for c in self.config.recent_connections
            if not (c['nas_ip'] == connection['nas_ip'] and 
                   c['share_name'] == connection['share_name'])
        ]
        
        # Add to front of list
        self.config.recent_connections.insert(0, connection)
        
        # Keep only last 10
        self.config.recent_connections = self.config.recent_connections[:10]
        
        self.save()
    
    def get_recent_connections(self) -> List[ServerConfig]:
        """Get list of recent connections."""
        
        connections = []
        
        for conn_data in self.config.recent_connections:
            try:
                config = ServerConfig(
                    nas_ip=conn_data.get('nas_ip', ''),
                    username=conn_data.get('username', ''),
                    password=conn_data.get('password', ''),
                    share_name=conn_data.get('share_name', ''),
                    base_path=conn_data.get('base_path', '/'),
                    folder_path=conn_data.get('folder_path', '')
                )
                connections.append(config)
            except Exception as e:
                self.logger.warning(f"Invalid recent connection: {e}")
        
        return connections
    
    def export_config(self, export_path: Path, include_sensitive: bool = False):
        """Export configuration for backup or sharing."""
        
        data = {
            'server': asdict(self.config.server),
            'app': asdict(self.config.app),
            'saved_searches': self.config.saved_searches
        }
        
        if not include_sensitive:
            # Remove sensitive data
            data['server']['password'] = ""
            data['server']['username'] = ""
        
        try:
            with open(export_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.logger.info(f"Configuration exported to {export_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to export configuration: {e}")
    
    def import_config(self, import_path: Path):
        """Import configuration from file."""
        
        try:
            with open(import_path, 'r') as f:
                data = json.load(f)
            
            # Import server config
            if 'server' in data:
                for key, value in data['server'].items():
                    if hasattr(self.config.server, key):
                        setattr(self.config.server, key, value)
            
            # Import app config
            if 'app' in data:
                for key, value in data['app'].items():
                    if hasattr(self.config.app, key):
                        setattr(self.config.app, key, value)
            
            # Import saved searches
            if 'saved_searches' in data:
                self.config.saved_searches = data['saved_searches']
            
            # Validate and save
            if self.validate():
                self.save()
                self.logger.info(f"Configuration imported from {import_path}")
            else:
                self.logger.error("Imported configuration is invalid")
                
        except Exception as e:
            self.logger.error(f"Failed to import configuration: {e}")