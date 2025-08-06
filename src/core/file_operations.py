#!/usr/bin/env python3
"""
Atomic file operations with rollback support and comprehensive error handling.
"""

import os
import tempfile
import shutil
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from contextlib import contextmanager
import platform

from .logging_config import get_logger, log_exception


class FileOperationError(Exception):
    """Custom exception for file operation failures."""
    pass


class FileBackup:
    """Manage file backups for rollback support."""
    
    def __init__(self, backup_dir: Optional[Path] = None):
        self.backup_dir = backup_dir or Path(tempfile.gettempdir()) / "pdf_modifier_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(__name__)
        self.backups: Dict[str, Path] = {}
        
    def create_backup(self, file_path: Path) -> str:
        """Create a backup of a file and return backup ID."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Generate unique backup ID
        backup_id = f"{file_path.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{id(self)}"
        backup_path = self.backup_dir / backup_id
        
        try:
            shutil.copy2(file_path, backup_path)
            self.backups[backup_id] = backup_path
            self.logger.info(f"Created backup: {backup_id} for {file_path}")
            return backup_id
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'create_backup', 'file': str(file_path)})
            raise FileOperationError(f"Failed to create backup: {e}")
    
    def restore_backup(self, backup_id: str, target_path: Path) -> bool:
        """Restore a file from backup."""
        if backup_id not in self.backups:
            raise ValueError(f"Backup not found: {backup_id}")
        
        backup_path = self.backups[backup_id]
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file missing: {backup_path}")
        
        try:
            shutil.copy2(backup_path, target_path)
            self.logger.info(f"Restored backup: {backup_id} to {target_path}")
            return True
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'restore_backup', 'backup_id': backup_id})
            raise FileOperationError(f"Failed to restore backup: {e}")
    
    def delete_backup(self, backup_id: str):
        """Delete a backup file."""
        if backup_id in self.backups:
            backup_path = self.backups[backup_id]
            try:
                if backup_path.exists():
                    backup_path.unlink()
                del self.backups[backup_id]
                self.logger.debug(f"Deleted backup: {backup_id}")
            except Exception as e:
                self.logger.warning(f"Failed to delete backup {backup_id}: {e}")
    
    def cleanup_old_backups(self, max_age_hours: int = 24):
        """Clean up backups older than specified hours."""
        current_time = datetime.now()
        
        for backup_file in self.backup_dir.glob("*"):
            try:
                file_time = datetime.fromtimestamp(backup_file.stat().st_mtime)
                age_hours = (current_time - file_time).total_seconds() / 3600
                
                if age_hours > max_age_hours:
                    backup_file.unlink()
                    self.logger.debug(f"Cleaned up old backup: {backup_file.name}")
                    
            except Exception as e:
                self.logger.warning(f"Error cleaning backup {backup_file}: {e}")


class FileValidator:
    """Validate file integrity and format."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
    
    def calculate_checksum(self, file_path: Path, algorithm: str = 'sha256') -> str:
        """Calculate file checksum."""
        hash_func = hashlib.new(algorithm)
        
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_func.update(chunk)
            return hash_func.hexdigest()
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'calculate_checksum', 'file': str(file_path)})
            raise FileOperationError(f"Failed to calculate checksum: {e}")
    
    def verify_pdf(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """Verify that a file is a valid PDF."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(5)
                if header != b'%PDF-':
                    return False, "Invalid PDF header"
                
                # Check for EOF marker
                f.seek(-128, os.SEEK_END)
                tail = f.read()
                if b'%%EOF' not in tail:
                    self.logger.warning(f"PDF missing EOF marker: {file_path}")
                
            return True, None
            
        except Exception as e:
            return False, str(e)
    
    def compare_files(self, file1: Path, file2: Path) -> bool:
        """Compare two files for equality."""
        try:
            if file1.stat().st_size != file2.stat().st_size:
                return False
            
            checksum1 = self.calculate_checksum(file1)
            checksum2 = self.calculate_checksum(file2)
            
            return checksum1 == checksum2
            
        except Exception as e:
            self.logger.error(f"Error comparing files: {e}")
            return False


class DateModifier:
    """Modify file dates with platform-specific implementations."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.platform = platform.system()
        
    def modify_file_dates(self, file_path: Path, modified_time: datetime, 
                         creation_time: Optional[datetime] = None) -> bool:
        """Modify file modification and creation dates."""
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            # Set modification time using touch command
            self._set_modification_time(file_path, modified_time)
            
            # Set creation time if provided and supported
            if creation_time:
                self._set_creation_time(file_path, creation_time)
            
            # Verify the changes
            stat = file_path.stat()
            actual_mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # Allow 1 minute tolerance
            if abs((actual_mtime - modified_time).total_seconds()) > 60:
                self.logger.warning(
                    f"Date verification mismatch. Expected: {modified_time}, Got: {actual_mtime}"
                )
            
            return True
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'modify_file_dates', 'file': str(file_path)})
            raise FileOperationError(f"Failed to modify file dates: {e}")
    
    def _set_modification_time(self, file_path: Path, timestamp: datetime):
        """Set file modification time using platform-specific method."""
        
        if self.platform in ['Linux', 'Darwin']:  # Unix-like systems
            # Use touch command
            touch_time = timestamp.strftime("%Y%m%d%H%M.%S")
            cmd = ['touch', '-t', touch_time, str(file_path)]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise FileOperationError(f"Touch command failed: {result.stderr}")
                
        elif self.platform == 'Windows':
            # Use PowerShell on Windows
            ps_command = f'''
                $file = Get-Item "{file_path}"
                $file.LastWriteTime = [DateTime]::Parse("{timestamp.isoformat()}")
            '''
            
            cmd = ['powershell', '-Command', ps_command]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise FileOperationError(f"PowerShell command failed: {result.stderr}")
                
        else:
            # Fallback to os.utime
            timestamp_seconds = timestamp.timestamp()
            os.utime(file_path, (timestamp_seconds, timestamp_seconds))
    
    def _set_creation_time(self, file_path: Path, timestamp: datetime):
        """Set file creation time (platform-specific)."""
        
        if self.platform == 'Darwin':  # macOS
            # Use SetFile command if available
            setfile_time = timestamp.strftime("%m/%d/%Y %H:%M:%S")
            cmd = ['SetFile', '-d', setfile_time, str(file_path)]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    self.logger.warning(f"SetFile command failed: {result.stderr}")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                self.logger.debug("SetFile command not available")
                
        elif self.platform == 'Windows':
            # Use PowerShell on Windows
            ps_command = f'''
                $file = Get-Item "{file_path}"
                $file.CreationTime = [DateTime]::Parse("{timestamp.isoformat()}")
            '''
            
            cmd = ['powershell', '-Command', ps_command]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    self.logger.warning(f"PowerShell command failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                self.logger.warning("PowerShell command timed out")


class AtomicFileOperation:
    """Context manager for atomic file operations with automatic rollback."""
    
    def __init__(self, target_file: Path, operation_name: str = "operation"):
        self.target_file = target_file
        self.operation_name = operation_name
        self.temp_file: Optional[Path] = None
        self.backup: Optional[FileBackup] = None
        self.backup_id: Optional[str] = None
        self.logger = get_logger(__name__)
        self.success = False
        
    def __enter__(self):
        """Setup atomic operation."""
        self.logger.info(f"Starting atomic {self.operation_name} on {self.target_file}")
        
        # Create backup if file exists
        if self.target_file.exists():
            self.backup = FileBackup()
            self.backup_id = self.backup.create_backup(self.target_file)
        
        # Create temporary file for operations
        fd, temp_path = tempfile.mkstemp(
            suffix=self.target_file.suffix,
            prefix=f"{self.target_file.stem}_temp_",
            dir=self.target_file.parent
        )
        os.close(fd)
        
        self.temp_file = Path(temp_path)
        
        # Copy original file to temp if it exists
        if self.target_file.exists():
            shutil.copy2(self.target_file, self.temp_file)
        
        return self.temp_file
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete or rollback operation."""
        
        if exc_type is None:
            # Operation succeeded, replace original with temp
            try:
                if self.target_file.exists():
                    self.target_file.unlink()
                    
                self.temp_file.rename(self.target_file)
                self.success = True
                
                self.logger.info(f"Atomic {self.operation_name} completed successfully")
                
                # Clean up backup
                if self.backup and self.backup_id:
                    self.backup.delete_backup(self.backup_id)
                    
            except Exception as e:
                self.logger.error(f"Failed to finalize {self.operation_name}: {e}")
                
                # Attempt rollback
                if self.backup and self.backup_id:
                    try:
                        self.backup.restore_backup(self.backup_id, self.target_file)
                        self.logger.info("Successfully rolled back to original file")
                    except Exception as rollback_error:
                        self.logger.critical(f"Rollback failed: {rollback_error}")
                        
                raise FileOperationError(f"Operation failed: {e}")
                
        else:
            # Operation failed, rollback
            self.logger.error(f"Atomic {self.operation_name} failed: {exc_val}")
            
            # Clean up temp file
            if self.temp_file and self.temp_file.exists():
                try:
                    self.temp_file.unlink()
                except:
                    pass
            
            # Restore from backup if needed
            if self.backup and self.backup_id and not self.target_file.exists():
                try:
                    self.backup.restore_backup(self.backup_id, self.target_file)
                    self.logger.info("Restored original file from backup")
                except Exception as restore_error:
                    self.logger.error(f"Failed to restore backup: {restore_error}")
        
        # Clean up temp file if still exists
        if self.temp_file and self.temp_file.exists():
            try:
                self.temp_file.unlink()
            except:
                pass


class FileOperationsManager:
    """High-level file operations manager."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.validator = FileValidator()
        self.date_modifier = DateModifier()
        self.backup_manager = FileBackup()
        
    @contextmanager
    def safe_file_operation(self, file_path: Path, operation_name: str = "operation"):
        """Context manager for safe file operations with validation and rollback."""
        
        file_path = Path(file_path)
        
        # Validate file exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Create checksum for verification
        original_checksum = self.validator.calculate_checksum(file_path)
        
        with AtomicFileOperation(file_path, operation_name) as temp_file:
            yield temp_file
            
            # Verify operation didn't corrupt the file
            if temp_file.exists():
                is_valid, error = self.validator.verify_pdf(temp_file)
                if not is_valid:
                    raise FileOperationError(f"Operation produced invalid PDF: {error}")
    
    def modify_pdf_dates(self, file_path: Path, new_date: datetime) -> bool:
        """Safely modify PDF file dates."""
        
        try:
            # First verify it's a valid PDF
            is_valid, error = self.validator.verify_pdf(file_path)
            if not is_valid:
                raise FileOperationError(f"Invalid PDF file: {error}")
            
            # Modify the dates
            success = self.date_modifier.modify_file_dates(file_path, new_date, new_date)
            
            if success:
                self.logger.info(f"Successfully modified dates for {file_path} to {new_date}")
            
            return success
            
        except Exception as e:
            log_exception(self.logger, e, {'file': str(file_path), 'new_date': str(new_date)})
            raise
    
    def cleanup(self):
        """Clean up old backups and temporary files."""
        self.backup_manager.cleanup_old_backups()