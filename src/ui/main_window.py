#!/usr/bin/env python3
"""
Main window UI for PDF Date Modifier application with comprehensive error handling.
"""

import sys
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QListWidget, QGroupBox,
    QMessageBox, QScrollArea, QComboBox, QDateTimeEdit,
    QSlider, QListWidgetItem, QProgressBar, QFormLayout,
    QToolBar, QMenu, QMenuBar, QStatusBar, QDialog,
    QDialogButtonBox, QTextEdit, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox
)
from PyQt6.QtCore import (
    Qt, QDateTime, QTimer, pyqtSignal, QSize
)
from PyQt6.QtGui import (
    QPixmap, QImage, QFont, QAction, QKeySequence, QIcon
)

from ..core import (
    get_logger, ConfigurationManager, ConnectionManager,
    ConnectionConfig, PDFProcessor, FileOperationsManager,
    ThreadManager, TaskPriority
)


class FileListItem(QListWidgetItem):
    """Custom list item for PDF files."""
    
    def __init__(self, file_info: Dict[str, Any]):
        super().__init__()
        self.file_info = file_info
        self.update_display()
    
    def update_display(self):
        """Update the display text."""
        filename = self.file_info['filename']
        date = self.file_info['modified'].strftime('%Y-%m-%d %H:%M')
        size_mb = self.file_info['size'] / (1024 * 1024)
        
        display_text = f"{filename}\n"
        display_text += f"  Modified: {date} | Size: {size_mb:.1f} MB"
        
        self.setText(display_text)


class ConnectionDialog(QDialog):
    """Dialog for managing connection settings."""
    
    def __init__(self, config_manager: ConfigurationManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.logger = get_logger(__name__)
        
        self.setWindowTitle("Connection Settings")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self.init_ui()
        self.load_current_config()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # Connection form
        form_layout = QFormLayout()
        
        self.nas_ip_input = QLineEdit()
        self.nas_ip_input.setPlaceholderText("192.168.1.100 or nas.local")
        form_layout.addRow("NAS IP/Host:", self.nas_ip_input)
        
        self.username_input = QLineEdit()
        form_layout.addRow("Username:", self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("Password:", self.password_input)
        
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("documents")
        form_layout.addRow("Share Name:", self.share_input)
        
        self.base_path_input = QLineEdit()
        self.base_path_input.setPlaceholderText("/Archive/Scanned")
        form_layout.addRow("Base Path:", self.base_path_input)
        
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("Optional - usually blank")
        form_layout.addRow("Domain:", self.domain_input)
        
        # Advanced settings
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QFormLayout()
        
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(445)
        advanced_layout.addRow("Port:", self.port_input)
        
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(5, 300)
        self.timeout_input.setValue(30)
        self.timeout_input.setSuffix(" seconds")
        advanced_layout.addRow("Timeout:", self.timeout_input)
        
        self.pool_size_input = QSpinBox()
        self.pool_size_input.setRange(1, 10)
        self.pool_size_input.setValue(3)
        advanced_layout.addRow("Connection Pool Size:", self.pool_size_input)
        
        advanced_group.setLayout(advanced_layout)
        
        # Recent connections
        recent_group = QGroupBox("Recent Connections")
        recent_layout = QVBoxLayout()
        
        self.recent_combo = QComboBox()
        self.recent_combo.currentIndexChanged.connect(self.load_recent_connection)
        recent_layout.addWidget(self.recent_combo)
        
        recent_group.setLayout(recent_layout)
        
        # Test connection button
        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self.test_connection)
        
        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        # Add to layout
        layout.addLayout(form_layout)
        layout.addWidget(advanced_group)
        layout.addWidget(recent_group)
        layout.addWidget(self.test_button)
        layout.addWidget(button_box)
        
        # Load recent connections
        self.load_recent_connections()
    
    def load_current_config(self):
        """Load current configuration into UI."""
        config = self.config_manager.config.server
        
        self.nas_ip_input.setText(config.nas_ip)
        self.username_input.setText(config.username)
        self.password_input.setText(config.password)
        self.share_input.setText(config.share_name)
        self.base_path_input.setText(config.base_path)
        self.domain_input.setText(config.domain)
        self.port_input.setValue(config.port)
        self.timeout_input.setValue(config.timeout)
    
    def load_recent_connections(self):
        """Load recent connections into combo box."""
        self.recent_combo.clear()
        self.recent_combo.addItem("-- Select Recent Connection --")
        
        for conn in self.config_manager.get_recent_connections():
            display = f"{conn.nas_ip} - {conn.share_name}"
            self.recent_combo.addItem(display, conn)
    
    def load_recent_connection(self, index: int):
        """Load selected recent connection."""
        if index <= 0:
            return
        
        conn = self.recent_combo.itemData(index)
        if conn:
            self.nas_ip_input.setText(conn.nas_ip)
            self.username_input.setText(conn.username)
            self.password_input.setText(conn.password)
            self.share_input.setText(conn.share_name)
            self.base_path_input.setText(conn.base_path)
    
    def test_connection(self):
        """Test the current connection settings."""
        config = self.get_connection_config()
        
        if not all([config.nas_ip, config.username, config.password, config.share_name]):
            QMessageBox.warning(self, "Missing Information",
                              "Please fill in all required fields.")
            return
        
        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")
        
        try:
            conn_manager = ConnectionManager(config)
            
            if conn_manager.test_connection():
                QMessageBox.information(self, "Success",
                                       "Connection successful!")
                self.logger.info("Connection test successful")
            else:
                QMessageBox.critical(self, "Failed",
                                   "Connection failed. Check your settings.")
                self.logger.error("Connection test failed")
            
            conn_manager.close()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection error: {e}")
            self.logger.error(f"Connection test error: {e}")
        
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Test Connection")
    
    def get_connection_config(self) -> ConnectionConfig:
        """Get connection configuration from UI."""
        return ConnectionConfig(
            nas_ip=self.nas_ip_input.text(),
            username=self.username_input.text(),
            password=self.password_input.text(),
            share_name=self.share_input.text(),
            domain=self.domain_input.text(),
            port=self.port_input.value(),
            timeout=self.timeout_input.value()
        )
    
    def accept(self):
        """Save configuration on accept."""
        config = self.get_connection_config()
        
        # Update configuration
        self.config_manager.config.server.nas_ip = config.nas_ip
        self.config_manager.config.server.username = config.username
        self.config_manager.config.server.password = config.password
        self.config_manager.config.server.share_name = config.share_name
        self.config_manager.config.server.base_path = self.base_path_input.text()
        self.config_manager.config.server.domain = config.domain
        self.config_manager.config.server.port = config.port
        self.config_manager.config.server.timeout = config.timeout
        
        # Save configuration
        self.config_manager.save()
        
        # Add to recent connections
        self.config_manager.add_recent_connection(self.config_manager.config.server)
        
        super().accept()


class LogViewerDialog(QDialog):
    """Dialog for viewing application logs."""
    
    def __init__(self, log_manager, parent=None):
        super().__init__(parent)
        self.log_manager = log_manager
        
        self.setWindowTitle("Log Viewer")
        self.setMinimumSize(800, 600)
        
        self.init_ui()
        self.load_logs()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # Tab widget for different log files
        self.tab_widget = QTabWidget()
        
        # Application log tab
        self.app_log_text = QTextEdit()
        self.app_log_text.setReadOnly(True)
        self.app_log_text.setFont(QFont("Courier", 10))
        self.tab_widget.addTab(self.app_log_text, "Application")
        
        # Error log tab
        self.error_log_text = QTextEdit()
        self.error_log_text.setReadOnly(True)
        self.error_log_text.setFont(QFont("Courier", 10))
        self.tab_widget.addTab(self.error_log_text, "Errors")
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.load_logs)
        controls_layout.addWidget(self.refresh_button)
        
        self.clear_button = QPushButton("Clear Old Logs")
        self.clear_button.clicked.connect(self.clear_old_logs)
        controls_layout.addWidget(self.clear_button)
        
        controls_layout.addStretch()
        
        self.auto_refresh_check = QCheckBox("Auto Refresh")
        self.auto_refresh_check.stateChanged.connect(self.toggle_auto_refresh)
        controls_layout.addWidget(self.auto_refresh_check)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        
        # Add to layout
        layout.addWidget(self.tab_widget)
        layout.addLayout(controls_layout)
        layout.addWidget(close_button)
        
        # Auto refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.load_logs)
    
    def load_logs(self):
        """Load log files into viewers."""
        log_files = self.log_manager.get_log_files()
        
        # Load application log
        try:
            app_log_path = log_files.get('application')
            if app_log_path and app_log_path.exists():
                with open(app_log_path, 'r') as f:
                    # Read last 1000 lines
                    lines = f.readlines()[-1000:]
                    self.app_log_text.setPlainText(''.join(lines))
                    # Scroll to bottom
                    self.app_log_text.verticalScrollBar().setValue(
                        self.app_log_text.verticalScrollBar().maximum()
                    )
        except Exception as e:
            self.app_log_text.setPlainText(f"Error loading log: {e}")
        
        # Load error log
        try:
            error_log_path = log_files.get('errors')
            if error_log_path and error_log_path.exists():
                with open(error_log_path, 'r') as f:
                    lines = f.readlines()[-500:]
                    self.error_log_text.setPlainText(''.join(lines))
                    self.error_log_text.verticalScrollBar().setValue(
                        self.error_log_text.verticalScrollBar().maximum()
                    )
        except Exception as e:
            self.error_log_text.setPlainText(f"Error loading log: {e}")
    
    def toggle_auto_refresh(self, checked: bool):
        """Toggle auto refresh."""
        if checked:
            self.refresh_timer.start(2000)  # Refresh every 2 seconds
        else:
            self.refresh_timer.stop()
    
    def clear_old_logs(self):
        """Clear old log files."""
        reply = QMessageBox.question(
            self, "Clear Logs",
            "Clear log files older than 30 days?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.log_manager.clean_old_logs(30)
            QMessageBox.information(self, "Success", "Old logs cleared.")
            self.load_logs()


class StatisticsDialog(QDialog):
    """Dialog for viewing application statistics."""
    
    def __init__(self, thread_manager: ThreadManager, connection_manager: Optional[ConnectionManager], parent=None):
        super().__init__(parent)
        self.thread_manager = thread_manager
        self.connection_manager = connection_manager
        
        self.setWindowTitle("Application Statistics")
        self.setMinimumSize(600, 400)
        
        self.init_ui()
        self.update_stats()
        
        # Auto update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_stats)
        self.update_timer.start(1000)
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # Statistics table
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(self.stats_table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
    
    def update_stats(self):
        """Update statistics display."""
        stats = []
        
        # Thread statistics
        thread_stats = self.thread_manager.get_statistics()
        stats.extend([
            ("Active Threads", str(thread_stats.get('active_threads', 0))),
            ("Tasks in Queue", str(thread_stats.get('queue_size', 0))),
            ("Tasks Completed", str(thread_stats.get('tasks_completed', 0))),
            ("Tasks Failed", str(thread_stats.get('tasks_failed', 0))),
            ("Success Rate", f"{thread_stats.get('success_rate', 0):.1%}"),
        ])
        
        # Connection statistics
        if self.connection_manager:
            conn_stats = self.connection_manager.get_health_stats()
            for conn_id, conn_data in conn_stats.items():
                if conn_data.get('is_healthy'):
                    status = "Healthy"
                else:
                    status = "Unhealthy"
                stats.append((f"{conn_id} Status", status))
                stats.append((f"{conn_id} Success Rate", 
                            f"{conn_data.get('success_rate', 0):.1%}"))
        
        # Update table
        self.stats_table.setRowCount(len(stats))
        for i, (metric, value) in enumerate(stats):
            self.stats_table.setItem(i, 0, QTableWidgetItem(metric))
            self.stats_table.setItem(i, 1, QTableWidgetItem(value))