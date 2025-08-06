#!/usr/bin/env python3
"""
Robust SMB connection manager with retry logic, connection pooling, and health checks.
"""

import time
import threading
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from contextlib import contextmanager
import socket

from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure

from .logging_config import get_logger, log_exception


@dataclass
class ConnectionConfig:
    """Configuration for SMB connection."""
    nas_ip: str
    username: str
    password: str
    share_name: str
    domain: str = ''
    port: int = 445
    use_ntlm_v2: bool = True
    is_direct_tcp: bool = True
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    keepalive_interval: int = 60
    max_idle_time: int = 300


class ConnectionHealth:
    """Track connection health metrics."""
    
    def __init__(self):
        self.last_success: Optional[datetime] = None
        self.last_failure: Optional[datetime] = None
        self.consecutive_failures: int = 0
        self.total_requests: int = 0
        self.total_failures: int = 0
        self.total_retries: int = 0
        self.average_response_time: float = 0.0
        self._response_times: List[float] = []
        self._lock = threading.Lock()
    
    def record_success(self, response_time: float):
        """Record a successful operation."""
        with self._lock:
            self.last_success = datetime.now()
            self.consecutive_failures = 0
            self.total_requests += 1
            self._response_times.append(response_time)
            if len(self._response_times) > 100:
                self._response_times.pop(0)
            self.average_response_time = sum(self._response_times) / len(self._response_times)
    
    def record_failure(self):
        """Record a failed operation."""
        with self._lock:
            self.last_failure = datetime.now()
            self.consecutive_failures += 1
            self.total_failures += 1
            self.total_requests += 1
    
    def record_retry(self):
        """Record a retry attempt."""
        with self._lock:
            self.total_retries += 1
    
    def is_healthy(self) -> bool:
        """Check if connection is considered healthy."""
        with self._lock:
            if self.consecutive_failures >= 5:
                return False
            if self.last_failure and self.last_success:
                if self.last_failure > self.last_success:
                    time_since_failure = datetime.now() - self.last_failure
                    if time_since_failure < timedelta(seconds=30):
                        return False
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get health statistics."""
        with self._lock:
            return {
                'last_success': self.last_success.isoformat() if self.last_success else None,
                'last_failure': self.last_failure.isoformat() if self.last_failure else None,
                'consecutive_failures': self.consecutive_failures,
                'total_requests': self.total_requests,
                'total_failures': self.total_failures,
                'total_retries': self.total_retries,
                'success_rate': (self.total_requests - self.total_failures) / self.total_requests if self.total_requests > 0 else 0,
                'average_response_time': self.average_response_time,
                'is_healthy': self.is_healthy()
            }


class SMBConnectionPool:
    """Connection pool for managing multiple SMB connections."""
    
    def __init__(self, config: ConnectionConfig, pool_size: int = 3):
        self.config = config
        self.pool_size = pool_size
        self.connections: List[Optional[SMBConnection]] = [None] * pool_size
        self.connection_locks: List[threading.Lock] = [threading.Lock() for _ in range(pool_size)]
        self.last_used: List[datetime] = [datetime.min for _ in range(pool_size)]
        self.health_trackers: List[ConnectionHealth] = [ConnectionHealth() for _ in range(pool_size)]
        self.logger = get_logger(__name__)
        self._shutdown = False
        
        # Start keepalive thread
        self.keepalive_thread = threading.Thread(target=self._keepalive_worker, daemon=True)
        self.keepalive_thread.start()
    
    def _create_connection(self, client_name: str = None) -> SMBConnection:
        """Create a new SMB connection."""
        client_name = client_name or f"PDF_MOD_{id(self)}"
        
        conn = SMBConnection(
            self.config.username,
            self.config.password,
            client_name,
            self.config.nas_ip,
            domain=self.config.domain,
            use_ntlm_v2=self.config.use_ntlm_v2,
            is_direct_tcp=self.config.is_direct_tcp
        )
        
        # Set socket timeout
        conn.sock_timeout = self.config.timeout
        
        return conn
    
    def _connect(self, conn: SMBConnection) -> bool:
        """Establish SMB connection with retries."""
        delay = self.config.retry_delay
        
        for attempt in range(self.config.max_retries):
            try:
                self.logger.debug(f"Connection attempt {attempt + 1}/{self.config.max_retries}")
                
                success = conn.connect(self.config.nas_ip, self.config.port, timeout=self.config.timeout)
                
                if success:
                    self.logger.info(f"Successfully connected to {self.config.nas_ip}")
                    return True
                else:
                    self.logger.warning(f"Authentication failed for {self.config.nas_ip}")
                    
            except socket.timeout:
                self.logger.warning(f"Connection timeout on attempt {attempt + 1}")
            except socket.error as e:
                self.logger.warning(f"Socket error on attempt {attempt + 1}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            
            if attempt < self.config.max_retries - 1:
                self.logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= self.config.retry_backoff
        
        return False
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        start_time = time.time()
        connection_index = -1
        connection = None
        
        try:
            # Find an available connection
            max_wait = 30
            wait_start = time.time()
            
            while time.time() - wait_start < max_wait:
                for i in range(self.pool_size):
                    if self.connection_locks[i].acquire(blocking=False):
                        connection_index = i
                        break
                
                if connection_index >= 0:
                    break
                    
                time.sleep(0.1)
            
            if connection_index < 0:
                raise TimeoutError("No available connections in pool")
            
            # Check if connection needs to be created or refreshed
            if (self.connections[connection_index] is None or 
                datetime.now() - self.last_used[connection_index] > timedelta(seconds=self.config.max_idle_time)):
                
                # Close old connection if exists
                if self.connections[connection_index]:
                    try:
                        self.connections[connection_index].close()
                    except:
                        pass
                
                # Create new connection
                self.logger.debug(f"Creating new connection for slot {connection_index}")
                conn = self._create_connection(f"PDF_MOD_{connection_index}")
                
                if not self._connect(conn):
                    raise ConnectionError(f"Failed to connect after {self.config.max_retries} attempts")
                
                self.connections[connection_index] = conn
            
            connection = self.connections[connection_index]
            self.last_used[connection_index] = datetime.now()
            
            # Test connection health
            try:
                connection.echo(b"ping")
            except:
                # Connection is dead, recreate it
                self.logger.warning(f"Connection {connection_index} failed health check, recreating...")
                conn = self._create_connection(f"PDF_MOD_{connection_index}")
                
                if not self._connect(conn):
                    raise ConnectionError("Failed to recreate connection")
                
                self.connections[connection_index] = conn
                connection = conn
            
            # Record success
            response_time = time.time() - start_time
            self.health_trackers[connection_index].record_success(response_time)
            
            yield connection
            
        except Exception as e:
            if connection_index >= 0:
                self.health_trackers[connection_index].record_failure()
            log_exception(self.logger, e, {'operation': 'get_connection'})
            raise
            
        finally:
            if connection_index >= 0:
                self.connection_locks[connection_index].release()
    
    def _keepalive_worker(self):
        """Background worker to maintain connection health."""
        while not self._shutdown:
            try:
                time.sleep(self.config.keepalive_interval)
                
                for i in range(self.pool_size):
                    if self.connection_locks[i].acquire(blocking=False):
                        try:
                            if self.connections[i] and datetime.now() - self.last_used[i] < timedelta(seconds=self.config.max_idle_time):
                                try:
                                    self.connections[i].echo(b"keepalive")
                                    self.logger.debug(f"Keepalive successful for connection {i}")
                                except:
                                    self.logger.warning(f"Keepalive failed for connection {i}")
                                    try:
                                        self.connections[i].close()
                                    except:
                                        pass
                                    self.connections[i] = None
                        finally:
                            self.connection_locks[i].release()
                            
            except Exception as e:
                self.logger.error(f"Keepalive worker error: {e}")
    
    def execute_with_retry(self, operation: Callable, *args, **kwargs):
        """Execute an operation with automatic retry on failure."""
        last_exception = None
        delay = self.config.retry_delay
        
        for attempt in range(self.config.max_retries):
            try:
                with self.get_connection() as conn:
                    result = operation(conn, *args, **kwargs)
                    return result
                    
            except OperationFailure as e:
                last_exception = e
                self.logger.warning(f"Operation failed (attempt {attempt + 1}): {e}")
                
                # Don't retry on certain errors
                if "STATUS_ACCESS_DENIED" in str(e) or "STATUS_OBJECT_NAME_NOT_FOUND" in str(e):
                    raise
                    
            except Exception as e:
                last_exception = e
                self.logger.warning(f"Operation error (attempt {attempt + 1}): {e}")
            
            if attempt < self.config.max_retries - 1:
                self.logger.info(f"Retrying operation in {delay} seconds...")
                time.sleep(delay)
                delay *= self.config.retry_backoff
        
        raise last_exception or Exception("Operation failed after all retries")
    
    def get_health_stats(self) -> Dict[str, Any]:
        """Get health statistics for all connections."""
        return {
            f"connection_{i}": self.health_trackers[i].get_stats()
            for i in range(self.pool_size)
        }
    
    def close_all(self):
        """Close all connections in the pool."""
        self._shutdown = True
        
        for i in range(self.pool_size):
            with self.connection_locks[i]:
                if self.connections[i]:
                    try:
                        self.connections[i].close()
                        self.logger.info(f"Closed connection {i}")
                    except Exception as e:
                        self.logger.error(f"Error closing connection {i}: {e}")
                    finally:
                        self.connections[i] = None


class ConnectionManager:
    """High-level connection manager with simplified interface."""
    
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.pool = SMBConnectionPool(config)
        self.logger = get_logger(__name__)
        
    def test_connection(self) -> bool:
        """Test if connection can be established."""
        try:
            with self.pool.get_connection() as conn:
                # Try to list root directory
                conn.listPath(self.config.share_name, '/')
                return True
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
    
    def list_files(self, path: str, pattern: str = "*.pdf") -> List[Dict[str, Any]]:
        """List files in a directory with retry logic."""
        
        def _list_operation(conn, path):
            files = []
            items = conn.listPath(self.config.share_name, path)
            
            for item in items:
                if item.isDirectory:
                    continue
                    
                # Check pattern match
                if pattern == "*" or item.filename.lower().endswith(pattern.replace("*", "")):
                    files.append({
                        'filename': item.filename,
                        'path': f"{path}/{item.filename}".replace('//', '/'),
                        'size': item.file_size,
                        'modified': datetime.fromtimestamp(item.last_write_time),
                        'created': datetime.fromtimestamp(item.create_time),
                    })
            
            return files
        
        return self.pool.execute_with_retry(_list_operation, path)
    
    def download_file(self, remote_path: str, local_path: str) -> bool:
        """Download a file from NAS."""
        
        def _download_operation(conn, remote_path, local_path):
            with open(local_path, 'wb') as f:
                conn.retrieveFile(self.config.share_name, remote_path, f)
            return True
        
        return self.pool.execute_with_retry(_download_operation, remote_path, local_path)
    
    def upload_file(self, local_path: str, remote_path: str, preserve_times: bool = False) -> bool:
        """Upload a file to NAS."""
        
        def _upload_operation(conn, local_path, remote_path):
            # Get the file's modification time before upload
            import os
            from datetime import datetime
            
            if preserve_times and os.path.exists(local_path):
                file_stat = os.stat(local_path)
                mod_time = file_stat.st_mtime
            else:
                mod_time = None
            
            with open(local_path, 'rb') as f:
                conn.storeFile(self.config.share_name, remote_path, f)
            
            # Try to set the modification time after upload if we're preserving times
            if preserve_times and mod_time:
                try:
                    # Convert to Windows file time (100-nanosecond intervals since Jan 1, 1601)
                    # SMB uses Windows file time format
                    import struct
                    windows_epoch = datetime(1601, 1, 1)
                    unix_epoch = datetime(1970, 1, 1)
                    epoch_diff = (unix_epoch - windows_epoch).total_seconds()
                    windows_time = int((mod_time + epoch_diff) * 10000000)
                    
                    # Try to set times using SMB - this might not work with all SMB servers
                    # conn.setPathInfo(self.config.share_name, remote_path, file_times=(0, 0, windows_time, windows_time))
                except Exception as e:
                    self.logger.debug(f"Could not preserve file times via SMB: {e}")
            
            return True
        
        return self.pool.execute_with_retry(_upload_operation, local_path, remote_path)
    
    def delete_file(self, remote_path: str) -> bool:
        """Delete a file from NAS."""
        
        def _delete_operation(conn, remote_path):
            conn.deleteFiles(self.config.share_name, remote_path)
            return True
        
        return self.pool.execute_with_retry(_delete_operation, remote_path)
    
    def modify_file_date(self, remote_path: str, new_date: datetime, update_metadata: bool = True) -> bool:
        """Download file, optionally update PDF metadata, modify its date locally, delete remote, and re-upload.
        
        This is an atomic operation that ensures the file date is properly set on the NAS.
        """
        
        import tempfile
        import os
        import subprocess
        from pathlib import Path
        
        def _modify_operation(conn, remote_path, new_date):
            # Create temp file
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            try:
                # Download file
                with open(temp_path, 'wb') as f:
                    conn.retrieveFile(self.config.share_name, remote_path, f)
                
                # Update PDF metadata if requested
                if update_metadata:
                    try:
                        import fitz  # PyMuPDF
                        doc = fitz.open(str(temp_path))
                        metadata = doc.metadata or {}
                        
                        # Format date for PDF metadata (D:YYYYMMDDHHmmSS)
                        pdf_date = new_date.strftime("D:%Y%m%d%H%M%S")
                        metadata['modDate'] = pdf_date
                        metadata['creationDate'] = pdf_date
                        
                        doc.set_metadata(metadata)
                        
                        # Save to new temp file
                        temp_modified = tempfile.mktemp(suffix='_meta.pdf')
                        doc.save(temp_modified)
                        doc.close()
                        
                        # Replace original temp with metadata-updated version
                        os.replace(temp_modified, str(temp_path))
                        
                        self.logger.debug(f"Updated PDF metadata for {remote_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not update PDF metadata: {e}")
                
                # Modify date locally using touch
                touch_time = new_date.strftime("%Y%m%d%H%M")
                touch_cmd = ['touch', '-t', touch_time, str(temp_path)]
                result = subprocess.run(touch_cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    raise Exception(f"Touch command failed: {result.stderr}")
                
                # Verify the date was set
                file_stat = os.stat(temp_path)
                actual_mtime = datetime.fromtimestamp(file_stat.st_mtime)
                expected_mtime = new_date.replace(second=0, microsecond=0)
                
                if abs((actual_mtime - expected_mtime).total_seconds()) > 60:
                    self.logger.warning(f"Date might not be set correctly. Expected: {expected_mtime}, Got: {actual_mtime}")
                else:
                    self.logger.debug(f"Successfully set file date to: {actual_mtime}")
                
                # Also try SetFile on macOS
                import platform
                if platform.system() == 'Darwin':
                    try:
                        setfile_time = new_date.strftime("%m/%d/%Y %H:%M:%S")
                        setfile_cmd = ['SetFile', '-d', setfile_time, '-m', setfile_time, str(temp_path)]
                        subprocess.run(setfile_cmd, capture_output=True, text=True, timeout=5)
                    except:
                        pass  # SetFile might not be available
                
                # Delete the remote file first
                try:
                    conn.deleteFiles(self.config.share_name, remote_path)
                    self.logger.debug(f"Deleted remote file: {remote_path}")
                except Exception as e:
                    self.logger.debug(f"Could not delete remote file (might not exist): {e}")
                
                # Upload the modified file - this should preserve the local file's modification time
                # but many NAS systems will override it to current time
                with open(temp_path, 'rb') as f:
                    conn.storeFile(self.config.share_name, remote_path, f)
                
                self.logger.info(f"Successfully modified date for {remote_path} to {new_date}")
                return True
                
            finally:
                # Clean up temp file
                try:
                    temp_path.unlink()
                except:
                    pass
        
        return self.pool.execute_with_retry(_modify_operation, remote_path, new_date)
    
    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on NAS."""
        
        try:
            def _exists_operation(conn, remote_path):
                # Try to get file attributes
                conn.getAttributes(self.config.share_name, remote_path)
                return True
            
            return self.pool.execute_with_retry(_exists_operation, remote_path)
        except:
            return False
    
    def get_health_stats(self) -> Dict[str, Any]:
        """Get connection health statistics."""
        return self.pool.get_health_stats()
    
    def close(self):
        """Close all connections."""
        self.pool.close_all()