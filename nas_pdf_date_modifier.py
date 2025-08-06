#!/usr/bin/env python3
"""
NAS PDF Date Modifier
A professional tool for modifying PDF file dates on network-attached storage.
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QGroupBox,
    QSplitter, QMessageBox, QScrollArea, QGridLayout, QComboBox,
    QDateTimeEdit, QSlider, QSizePolicy, QListWidgetItem, QFrame,
    QProgressBar, QToolButton, QButtonGroup, QRadioButton, QSpacerItem,
    QAbstractItemView, QStyle, QStyleOptionSlider, QToolBar
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QDateTime, QDate, QTime, QTimer, 
    QPropertyAnimation, QEasingCurve, QSize, QRect
)
from PyQt6.QtGui import (
    QPixmap, QImage, QFont, QIcon, QPalette, QColor, QAction,
    QKeySequence, QFontDatabase, QPainter, QBrush, QPen
)

from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure
import fitz  # PyMuPDF


# DEFAULT SETTINGS - MODIFY THESE AS NEEDED
DEFAULT_SETTINGS = {
    'nas_ip': '',  # e.g., '192.168.1.100'
    'username': '',  # e.g., 'admin'
    'password': '',  # e.g., 'password123'
    'share_name': '',  # e.g., 'documents'
    'base_path': '',  # e.g., '/Archive/Scanned'
}

# UI Color Scheme
COLORS = {
    'primary': '#2C3E50',
    'secondary': '#34495E',
    'accent': '#3498DB',
    'success': '#27AE60',
    'warning': '#F39C12',
    'danger': '#E74C3C',
    'light': '#ECF0F1',
    'dark': '#1A252F',
    'pdf_bg': '#525659',
    'hover': '#3A4F66'
}


class StyledButton(QPushButton):
    """Custom styled button with hover effects."""
    def __init__(self, text, color='primary', icon=None):
        super().__init__(text)
        self.color = COLORS.get(color, COLORS['primary'])
        self.setIcon(icon if icon else QIcon())
        self.update_style()
        
    def update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['hover']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['dark']};
            }}
            QPushButton:disabled {{
                background-color: #95A5A6;
                color: #BDC3C7;
            }}
        """)


class FileListItem(QListWidgetItem):
    """Custom list item with better formatting."""
    def __init__(self, file_info):
        super().__init__()
        self.file_info = file_info
        self.update_display()
        
    def update_display(self):
        filename = self.file_info['filename']
        date = self.file_info['modified'].strftime('%Y-%m-%d %H:%M')
        size_mb = self.file_info['size'] / (1024 * 1024)
        self.setText(f"{filename}\n  📅 {date}  📄 {size_mb:.1f} MB")


class NASConnection:
    def __init__(self, nas_ip, username, password, share_name, domain=''):
        self.nas_ip = nas_ip
        self.username = username
        self.password = password
        self.share_name = share_name
        self.domain = domain
        self.connection = None
        self.client_name = 'PDF_DATE_MODIFIER'
        
    def connect(self):
        """Establish SMB connection using NTLM with direct TCP."""
        try:
            self.connection = SMBConnection(
                self.username,
                self.password,
                self.client_name,
                self.nas_ip,
                domain=self.domain,
                use_ntlm_v2=True,
                is_direct_tcp=True
            )
            
            success = self.connection.connect(self.nas_ip, 445)
            if not success:
                raise Exception("Failed to authenticate with NAS")
            
            return True
        except Exception as e:
            raise Exception(f"Connection failed: {str(e)}")
    
    def disconnect(self):
        """Close the SMB connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def list_pdf_files(self, path):
        """List all PDF files in the given path."""
        if not self.connection:
            raise Exception("Not connected to NAS")
        
        try:
            files = []
            shared_files = self.connection.listPath(self.share_name, path)
            
            for file_info in shared_files:
                if not file_info.isDirectory and file_info.filename.lower().endswith('.pdf'):
                    files.append({
                        'filename': file_info.filename,
                        'path': os.path.join(path, file_info.filename),
                        'size': file_info.file_size,
                        'modified': datetime.fromtimestamp(file_info.last_write_time)
                    })
            
            return sorted(files, key=lambda x: x['filename'])
        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")
    
    def download_file(self, remote_path, local_path):
        """Download a file from NAS to local temporary location."""
        if not self.connection:
            raise Exception("Not connected to NAS")
        
        try:
            with open(local_path, 'wb') as local_file:
                self.connection.retrieveFile(self.share_name, remote_path, local_file)
            return True
        except Exception as e:
            raise Exception(f"Failed to download file: {str(e)}")
    
    def upload_file(self, local_path, remote_path):
        """Upload a file from local to NAS."""
        if not self.connection:
            raise Exception("Not connected to NAS")
        
        try:
            with open(local_path, 'rb') as local_file:
                self.connection.storeFile(self.share_name, remote_path, local_file)
            return True
        except Exception as e:
            raise Exception(f"Failed to upload file: {str(e)}")
    
    def set_file_times(self, remote_path, modified_time):
        """Set the modification time of a file on the NAS."""
        if not self.connection:
            raise Exception("Not connected to NAS")
        
        try:
            timestamp = int(modified_time.timestamp())
            
            # Try SMB2 setPathInfo first
            self.connection.setPathInfo(
                self.share_name,
                remote_path,
                last_write_time=timestamp
            )
            return True
        except Exception as e:
            # Fallback: download, modify locally, re-upload
            temp_path = tempfile.mktemp(suffix='.pdf')
            try:
                self.download_file(remote_path, temp_path)
                os.utime(temp_path, (timestamp, timestamp))
                self.upload_file(temp_path, remote_path)
                return True
            except Exception as upload_error:
                raise Exception(f"Failed to set file time: {str(upload_error)}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)


class ConnectionThread(QThread):
    success = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, nas_ip, username, password, share_name, path):
        super().__init__()
        self.nas_ip = nas_ip
        self.username = username
        self.password = password
        self.share_name = share_name
        self.path = path
        self.nas_connection = None
    
    def run(self):
        try:
            self.progress.emit("Establishing connection...")
            self.nas_connection = NASConnection(
                self.nas_ip, self.username, self.password, self.share_name
            )
            
            self.progress.emit("Authenticating...")
            self.nas_connection.connect()
            
            self.progress.emit("Loading file list...")
            files = self.nas_connection.list_pdf_files(self.path or '/')
            
            self.success.emit(files)
        except Exception as e:
            self.error.emit(str(e))
    
    def get_connection(self):
        return self.nas_connection


class PDFLoadThread(QThread):
    loaded = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    
    def __init__(self, nas_connection, file_info):
        super().__init__()
        self.nas_connection = nas_connection
        self.file_info = file_info
    
    def run(self):
        try:
            self.progress.emit(25)
            temp_path = tempfile.mktemp(suffix='.pdf')
            
            self.progress.emit(50)
            self.nas_connection.download_file(self.file_info['path'], temp_path)
            
            self.progress.emit(75)
            pdf_doc = fitz.open(temp_path)
            
            self.progress.emit(100)
            self.loaded.emit({
                'doc': pdf_doc,
                'temp_path': temp_path,
                'file_info': self.file_info
            })
        except Exception as e:
            self.error.emit(str(e))


class DateModifyThread(QThread):
    success = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, nas_connection, remote_path, new_date):
        super().__init__()
        self.nas_connection = nas_connection
        self.remote_path = remote_path
        self.new_date = new_date
    
    def run(self):
        try:
            self.nas_connection.set_file_times(self.remote_path, self.new_date)
            self.success.emit()
        except Exception as e:
            self.error.emit(str(e))


class PDFViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.nas_connection = None
        self.pdf_files = []
        self.current_file_index = -1
        self.current_pdf_doc = None
        self.current_pdf_path = None
        self.temp_pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        self.zoom_level = 100
        self.fit_to_page = True
        self.connection_status = False
        
        self.init_ui()
        self.setup_shortcuts()
        self.load_defaults()
        self.apply_theme()
    
    def apply_theme(self):
        """Apply the professional dark theme."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['light']};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 2px solid {COLORS['secondary']};
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: {COLORS['primary']};
            }}
            QListWidget {{
                border: 1px solid {COLORS['secondary']};
                border-radius: 4px;
                background-color: white;
                alternate-background-color: {COLORS['light']};
                outline: none;
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COLORS['light']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['hover']};
                color: white;
            }}
            QLineEdit {{
                min-height: 28px;
                padding: 8px;
                border: 1px solid {COLORS['secondary']};
                border-radius: 4px;
                background-color: white;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['accent']};
            }}
            QDateTimeEdit {{
                min-height: 32px;
                padding: 8px;
                border: 1px solid {COLORS['secondary']};
                border-radius: 4px;
                background-color: white;
                font-size: 13px;
            }}
            QDateTimeEdit:focus {{
                border: 2px solid {COLORS['accent']};
            }}
            QDateTimeEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {COLORS['secondary']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['accent']};
                border: 1px solid {COLORS['primary']};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {COLORS['primary']};
            }}
            QProgressBar {{
                border: 1px solid {COLORS['secondary']};
                border-radius: 4px;
                text-align: center;
                background-color: white;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 3px;
            }}
            QStatusBar {{
                background-color: {COLORS['primary']};
                color: white;
                font-size: 12px;
            }}
            QScrollArea {{
                border: 1px solid {COLORS['secondary']};
                border-radius: 4px;
            }}
            QLabel {{
                color: {COLORS['dark']};
            }}
            QMessageBox {{
                background-color: white;
            }}
        """)
    
    def load_defaults(self):
        """Load default settings into the UI."""
        self.nas_ip_input.setText(DEFAULT_SETTINGS.get('nas_ip', ''))
        self.username_input.setText(DEFAULT_SETTINGS.get('username', ''))
        self.password_input.setText(DEFAULT_SETTINGS.get('password', ''))
        self.share_input.setText(DEFAULT_SETTINGS.get('share_name', ''))
        self.base_path_input.setText(DEFAULT_SETTINGS.get('base_path', ''))
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts for better UX."""
        # Navigation shortcuts
        QAction("Next Page", self, triggered=self.next_page, 
                shortcut=QKeySequence("Right")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Previous Page", self, triggered=self.prev_page,
                shortcut=QKeySequence("Left")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Next File", self, triggered=self.next_file,
                shortcut=QKeySequence("Ctrl+Right")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Previous File", self, triggered=self.prev_file,
                shortcut=QKeySequence("Ctrl+Left")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        
        # Zoom shortcuts
        QAction("Zoom In", self, triggered=self.zoom_in,
                shortcut=QKeySequence("Ctrl++")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Zoom Out", self, triggered=self.zoom_out,
                shortcut=QKeySequence("Ctrl+-")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Fit to Page", self, triggered=self.fit_to_page_clicked,
                shortcut=QKeySequence("Ctrl+0")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        
        # Action shortcuts
        QAction("Modify Date", self, triggered=self.modify_file_date,
                shortcut=QKeySequence("Ctrl+M")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        QAction("Connect", self, triggered=self.connect_to_nas,
                shortcut=QKeySequence("Ctrl+K")).setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    
    def init_ui(self):
        self.setWindowTitle("PDF Date Modifier Pro")
        self.setGeometry(100, 100, 1500, 950)
        
        # Set application icon if available
        self.setWindowIcon(QIcon())
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 5)
        
        # Top Section: Connection Panel
        self.create_connection_panel(main_layout)
        
        # Middle Section: Main Content Area
        self.create_main_content(main_layout)
        
        # Bottom Section: Action Panel
        self.create_action_panel(main_layout)
        
        # Status bar with progress indicator
        self.create_status_bar()
    
    def create_connection_panel(self, parent_layout):
        """Create the connection panel with improved layout."""
        connection_frame = QFrame()
        connection_frame.setMaximumHeight(140)
        connection_frame.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        
        connection_layout = QVBoxLayout(connection_frame)
        
        # Title and status indicator
        header_layout = QHBoxLayout()
        
        title_label = QLabel("🔌 Network Connection")
        title_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS['primary']};")
        header_layout.addWidget(title_label)
        
        self.connection_indicator = QLabel("⚫ Disconnected")
        self.connection_indicator.setStyleSheet("font-size: 14px; color: #7F8C8D;")
        header_layout.addWidget(self.connection_indicator)
        
        header_layout.addStretch()
        connection_layout.addLayout(header_layout)
        
        # Connection fields in a grid
        fields_layout = QGridLayout()
        fields_layout.setSpacing(8)
        
        # Row 1: Core connection details
        fields_layout.addWidget(QLabel("Server:"), 0, 0)
        self.nas_ip_input = QLineEdit()
        self.nas_ip_input.setPlaceholderText("192.168.1.100")
        self.nas_ip_input.setFixedHeight(35)
        self.nas_ip_input.setMaximumWidth(150)
        fields_layout.addWidget(self.nas_ip_input, 0, 1)
        
        fields_layout.addWidget(QLabel("Username:"), 0, 2)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("admin")
        self.username_input.setFixedHeight(35)
        self.username_input.setMaximumWidth(150)
        fields_layout.addWidget(self.username_input, 0, 3)
        
        fields_layout.addWidget(QLabel("Password:"), 0, 4)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setFixedHeight(35)
        self.password_input.setMaximumWidth(150)
        fields_layout.addWidget(self.password_input, 0, 5)
        
        # Row 2: Path details
        fields_layout.addWidget(QLabel("Share:"), 1, 0)
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("documents")
        self.share_input.setFixedHeight(35)
        self.share_input.setMaximumWidth(150)
        fields_layout.addWidget(self.share_input, 1, 1)
        
        fields_layout.addWidget(QLabel("Base Path:"), 1, 2)
        self.base_path_input = QLineEdit()
        self.base_path_input.setPlaceholderText("/Archive/Scanned")
        self.base_path_input.setFixedHeight(35)
        self.base_path_input.setMaximumWidth(200)
        fields_layout.addWidget(self.base_path_input, 1, 3, 1, 2)
        
        fields_layout.addWidget(QLabel("Folder:"), 1, 5)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("2024")
        self.folder_input.setFixedHeight(35)
        self.folder_input.setMaximumWidth(150)
        fields_layout.addWidget(self.folder_input, 1, 6)
        
        # Connect button
        self.connect_button = StyledButton("Connect", 'accent')
        self.connect_button.clicked.connect(self.connect_to_nas)
        self.connect_button.setMinimumWidth(100)
        fields_layout.addWidget(self.connect_button, 1, 7)
        
        fields_layout.setColumnStretch(8, 1)
        connection_layout.addLayout(fields_layout)
        
        parent_layout.addWidget(connection_frame)
    
    def create_main_content(self, parent_layout):
        """Create the main content area with file list and PDF viewer."""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left Panel: File Browser
        file_frame = QFrame()
        file_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        file_layout = QVBoxLayout(file_frame)
        
        # File browser header
        browser_header = QHBoxLayout()
        browser_label = QLabel("📁 PDF Files")
        browser_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLORS['primary']};")
        browser_header.addWidget(browser_label)
        
        self.file_count_label = QLabel("0 files")
        self.file_count_label.setStyleSheet("font-size: 12px; color: #7F8C8D;")
        browser_header.addWidget(self.file_count_label)
        browser_header.addStretch()
        
        file_layout.addLayout(browser_header)
        
        # Search/filter bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search files...")
        self.search_input.setFixedHeight(35)
        self.search_input.textChanged.connect(self.filter_files)
        file_layout.addWidget(self.search_input)
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.itemSelectionChanged.connect(self.on_file_select)
        file_layout.addWidget(self.file_list)
        
        # Quick stats
        self.stats_label = QLabel("Select a file to view details")
        self.stats_label.setStyleSheet("font-size: 11px; color: #7F8C8D; padding: 5px;")
        file_layout.addWidget(self.stats_label)
        
        file_frame.setMaximumWidth(400)
        splitter.addWidget(file_frame)
        
        # Right Panel: PDF Viewer
        viewer_frame = QFrame()
        viewer_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        viewer_layout = QVBoxLayout(viewer_frame)
        
        # Viewer header with controls
        self.create_viewer_controls(viewer_layout)
        
        # PDF display area
        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setWidgetResizable(False)
        self.pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS['pdf_bg']};
                border: none;
                border-radius: 4px;
            }}
        """)
        
        self.pdf_label = QLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setText("📄 No PDF loaded\n\nSelect a file from the list to preview")
        self.pdf_label.setStyleSheet("""
            QLabel {
                background-color: white;
                padding: 20px;
                color: #7F8C8D;
                font-size: 14px;
            }
        """)
        self.pdf_scroll.setWidget(self.pdf_label)
        
        viewer_layout.addWidget(self.pdf_scroll)
        
        # Loading progress bar
        self.load_progress = QProgressBar()
        self.load_progress.setMaximumHeight(3)
        self.load_progress.setTextVisible(False)
        self.load_progress.hide()
        viewer_layout.addWidget(self.load_progress)
        
        splitter.addWidget(viewer_frame)
        
        # Set splitter sizes
        splitter.setSizes([400, 1100])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        
        parent_layout.addWidget(splitter)
    
    def create_viewer_controls(self, parent_layout):
        """Create the PDF viewer control panel."""
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(15)
        
        # Page navigation
        nav_frame = QFrame()
        nav_frame.setStyleSheet("""
            QFrame {
                background-color: #F8F9FA;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setSpacing(5)
        
        self.prev_page_btn = QPushButton("◀")
        self.prev_page_btn.clicked.connect(self.prev_page)
        self.prev_page_btn.setEnabled(False)
        self.prev_page_btn.setMaximumWidth(30)
        nav_layout.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Page: 0/0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(100)
        self.page_label.setStyleSheet("font-weight: bold;")
        nav_layout.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("▶")
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)
        self.next_page_btn.setMaximumWidth(30)
        nav_layout.addWidget(self.next_page_btn)
        
        controls_layout.addWidget(nav_frame)
        
        controls_layout.addStretch()
        
        # Zoom controls
        zoom_frame = QFrame()
        zoom_frame.setStyleSheet("""
            QFrame {
                background-color: #F8F9FA;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        zoom_layout = QHBoxLayout(zoom_frame)
        zoom_layout.setSpacing(10)
        
        zoom_layout.addWidget(QLabel("🔍"))
        
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_out_btn.setMaximumWidth(25)
        zoom_layout.addWidget(self.zoom_out_btn)
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(25)
        self.zoom_slider.setMaximum(400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self.zoom_slider.setMinimumWidth(120)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        zoom_layout.addWidget(self.zoom_slider)
        
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_in_btn.setMaximumWidth(25)
        zoom_layout.addWidget(self.zoom_in_btn)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(45)
        self.zoom_label.setStyleSheet("font-weight: bold;")
        zoom_layout.addWidget(self.zoom_label)
        
        self.fit_button = QPushButton("⊡ Fit")
        self.fit_button.clicked.connect(self.fit_to_page_clicked)
        self.fit_button.setCheckable(True)
        self.fit_button.setChecked(True)
        zoom_layout.addWidget(self.fit_button)
        
        controls_layout.addWidget(zoom_frame)
        
        parent_layout.addLayout(controls_layout)
    
    def create_action_panel(self, parent_layout):
        """Create the bottom action panel for date modification."""
        action_frame = QFrame()
        action_frame.setMaximumHeight(100)
        action_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        action_layout = QHBoxLayout(action_frame)
        action_layout.setSpacing(20)
        
        # Current date display
        date_info_layout = QVBoxLayout()
        date_info_label = QLabel("Current File Date")
        date_info_label.setStyleSheet("font-size: 11px; color: #7F8C8D;")
        date_info_layout.addWidget(date_info_label)
        
        self.current_date_label = QLabel("No file selected")
        self.current_date_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS['primary']};
            padding: 5px;
            background-color: #F8F9FA;
            border-radius: 4px;
        """)
        date_info_layout.addWidget(self.current_date_label)
        action_layout.addLayout(date_info_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #E0E0E0;")
        action_layout.addWidget(separator)
        
        # New date selection
        new_date_layout = QVBoxLayout()
        new_date_label = QLabel("Set New Date")
        new_date_label.setStyleSheet("font-size: 11px; color: #7F8C8D;")
        new_date_layout.addWidget(new_date_label)
        
        date_input_layout = QHBoxLayout()
        
        self.date_time_edit = QDateTimeEdit()
        self.date_time_edit.setCalendarPopup(True)
        self.date_time_edit.setDateTime(QDateTime.currentDateTime())
        self.date_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.date_time_edit.setMinimumWidth(200)
        self.date_time_edit.setFixedHeight(40)
        self.date_time_edit.setStyleSheet("font-size: 14px;")
        date_input_layout.addWidget(self.date_time_edit)
        
        # Quick date buttons
        self.today_btn = QPushButton("Today")
        self.today_btn.clicked.connect(lambda: self.date_time_edit.setDateTime(QDateTime.currentDateTime()))
        date_input_layout.addWidget(self.today_btn)
        
        new_date_layout.addLayout(date_input_layout)
        action_layout.addLayout(new_date_layout)
        
        action_layout.addStretch()
        
        # Action buttons
        button_layout = QVBoxLayout()
        
        self.modify_button = StyledButton("✓ Apply Date", 'success')
        self.modify_button.clicked.connect(self.modify_file_date)
        self.modify_button.setEnabled(False)
        self.modify_button.setMinimumWidth(150)
        button_layout.addWidget(self.modify_button)
        
        nav_btn_layout = QHBoxLayout()
        
        self.prev_file_button = QPushButton("← Previous")
        self.prev_file_button.clicked.connect(self.prev_file)
        self.prev_file_button.setEnabled(False)
        nav_btn_layout.addWidget(self.prev_file_button)
        
        self.next_file_button = QPushButton("Next →")
        self.next_file_button.clicked.connect(self.next_file)
        self.next_file_button.setEnabled(False)
        nav_btn_layout.addWidget(self.next_file_button)
        
        button_layout.addLayout(nav_btn_layout)
        action_layout.addLayout(button_layout)
        
        parent_layout.addWidget(action_frame)
    
    def create_status_bar(self):
        """Create an enhanced status bar."""
        status = self.statusBar()
        status.showMessage("⚡ Ready - Press Ctrl+K to connect")
        
        # Add permanent widgets to status bar
        self.progress_label = QLabel("")
        status.addPermanentWidget(self.progress_label)
    
    def filter_files(self, text):
        """Filter the file list based on search input."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())
    
    def update_connection_status(self, connected):
        """Update the connection status indicator."""
        if connected:
            self.connection_indicator.setText("🟢 Connected")
            self.connection_indicator.setStyleSheet(f"font-size: 14px; color: {COLORS['success']};")
            self.connect_button.setText("Disconnect")
            self.connect_button.color = COLORS['danger']
            self.connect_button.update_style()
        else:
            self.connection_indicator.setText("⚫ Disconnected")
            self.connection_indicator.setStyleSheet("font-size: 14px; color: #7F8C8D;")
            self.connect_button.setText("Connect")
            self.connect_button.color = COLORS['accent']
            self.connect_button.update_style()
    
    def connect_to_nas(self):
        if self.connection_status:
            self.disconnect_from_nas()
            return
            
        nas_ip = self.nas_ip_input.text()
        username = self.username_input.text()
        password = self.password_input.text()
        share = self.share_input.text()
        base_path = self.base_path_input.text()
        folder = self.folder_input.text()
        
        # Combine paths
        if base_path and folder:
            full_path = os.path.join(base_path, folder)
        elif base_path:
            full_path = base_path
        elif folder:
            full_path = folder
        else:
            full_path = '/'
        
        if not full_path.startswith('/'):
            full_path = '/' + full_path
        
        if not all([nas_ip, username, password, share]):
            QMessageBox.warning(self, "Missing Information", 
                               "Please fill in Server, Username, Password, and Share fields.")
            return
        
        self.statusBar().showMessage(f"🔄 Connecting to {nas_ip}...")
        self.connect_button.setEnabled(False)
        
        self.connection_thread = ConnectionThread(nas_ip, username, password, share, full_path)
        self.connection_thread.success.connect(self.on_connection_success)
        self.connection_thread.error.connect(self.on_connection_error)
        self.connection_thread.progress.connect(lambda msg: self.statusBar().showMessage(f"🔄 {msg}"))
        self.connection_thread.start()
    
    def on_connection_success(self, files):
        self.nas_connection = self.connection_thread.get_connection()
        self.pdf_files = files
        self.connection_status = True
        
        self.update_connection_status(True)
        self.connect_button.setEnabled(True)
        
        # Update file list
        self.file_list.clear()
        for file_info in files:
            item = FileListItem(file_info)
            self.file_list.addItem(item)
        
        self.file_count_label.setText(f"{len(files)} files")
        self.statusBar().showMessage(f"✅ Connected - Found {len(files)} PDF files")
        
        if files:
            self.file_list.setCurrentRow(0)
    
    def on_connection_error(self, error_msg):
        self.statusBar().showMessage(f"❌ Connection failed: {error_msg}")
        self.connect_button.setEnabled(True)
        QMessageBox.critical(self, "Connection Error", error_msg)
    
    def disconnect_from_nas(self):
        if self.nas_connection:
            self.nas_connection.disconnect()
            self.nas_connection = None
        
        self.connection_status = False
        self.update_connection_status(False)
        
        self.file_list.clear()
        self.pdf_files = []
        self.file_count_label.setText("0 files")
        self.clear_pdf_viewer()
        
        self.statusBar().showMessage("⚡ Disconnected from NAS")
    
    def on_file_select(self):
        current_item = self.file_list.currentItem()
        if not current_item or not isinstance(current_item, FileListItem):
            return
        
        self.current_file_index = self.file_list.currentRow()
        file_info = current_item.file_info
        
        # Update stats
        size_mb = file_info['size'] / (1024 * 1024)
        self.stats_label.setText(f"Size: {size_mb:.2f} MB | Modified: {file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Update dates
        modified_date = file_info['modified']
        self.current_date_label.setText(modified_date.strftime('%Y-%m-%d %H:%M:%S'))
        
        qt_datetime = QDateTime(
            QDate(modified_date.year, modified_date.month, modified_date.day),
            QTime(modified_date.hour, modified_date.minute, modified_date.second)
        )
        self.date_time_edit.setDateTime(qt_datetime)
        
        self.statusBar().showMessage(f"📄 Loading {file_info['filename']}...")
        
        # Show progress bar
        self.load_progress.show()
        self.load_progress.setValue(0)
        
        # Load PDF
        self.pdf_thread = PDFLoadThread(self.nas_connection, file_info)
        self.pdf_thread.loaded.connect(self.on_pdf_loaded)
        self.pdf_thread.error.connect(self.on_pdf_error)
        self.pdf_thread.progress.connect(self.load_progress.setValue)
        self.pdf_thread.start()
    
    def on_pdf_loaded(self, data):
        # Clean up previous PDF
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
        
        self.current_pdf_doc = data['doc']
        self.temp_pdf_path = data['temp_path']
        self.current_pdf_path = data['file_info']['path']
        self.total_pages = len(self.current_pdf_doc)
        self.current_page = 0
        
        # Reset zoom
        self.fit_to_page = True
        self.fit_button.setChecked(True)
        
        self.display_pdf_page()
        
        # Hide progress bar
        self.load_progress.hide()
        
        self.statusBar().showMessage(f"✅ Loaded {data['file_info']['filename']} ({self.total_pages} pages)")
        self.modify_button.setEnabled(True)
        self.next_file_button.setEnabled(self.current_file_index < len(self.pdf_files) - 1)
        self.prev_file_button.setEnabled(self.current_file_index > 0)
    
    def on_pdf_error(self, error_msg):
        self.load_progress.hide()
        QMessageBox.critical(self, "Error", f"Failed to load PDF: {error_msg}")
        self.statusBar().showMessage("❌ Error loading PDF")
    
    def calculate_fit_zoom(self, page):
        """Calculate zoom to fit page in viewport."""
        page_rect = page.rect
        page_width = page_rect.width
        page_height = page_rect.height
        
        viewport = self.pdf_scroll.viewport()
        available_width = viewport.width() - 40
        available_height = viewport.height() - 40
        
        zoom_width = available_width / page_width
        zoom_height = available_height / page_height
        
        return min(zoom_width, zoom_height)
    
    def display_pdf_page(self):
        if not self.current_pdf_doc:
            return
        
        try:
            page = self.current_pdf_doc[self.current_page]
            
            if self.fit_to_page:
                zoom = self.calculate_fit_zoom(page)
                self.zoom_level = int(zoom * 100)
                self.zoom_slider.blockSignals(True)
                self.zoom_slider.setValue(self.zoom_level)
                self.zoom_slider.blockSignals(False)
                self.zoom_label.setText(f"{self.zoom_level}%")
            else:
                zoom = self.zoom_level / 100.0
            
            # Render page
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            img_data = pix.tobytes("ppm")
            qimg = QImage.fromData(img_data)
            
            pixmap = QPixmap.fromImage(qimg)
            self.pdf_label.setPixmap(pixmap)
            self.pdf_label.resize(pixmap.size())
            
            # Update controls
            self.page_label.setText(f"Page: {self.current_page + 1}/{self.total_pages}")
            self.prev_page_btn.setEnabled(self.current_page > 0)
            self.next_page_btn.setEnabled(self.current_page < self.total_pages - 1)
            
        except Exception as e:
            QMessageBox.critical(self, "Display Error", f"Failed to display page: {str(e)}")
    
    def on_zoom_changed(self, value):
        self.zoom_level = value
        self.zoom_label.setText(f"{value}%")
        self.fit_to_page = False
        self.fit_button.setChecked(False)
        if self.current_pdf_doc:
            self.display_pdf_page()
    
    def zoom_in(self):
        new_zoom = min(self.zoom_level + 25, 400)
        self.zoom_slider.setValue(new_zoom)
    
    def zoom_out(self):
        new_zoom = max(self.zoom_level - 25, 25)
        self.zoom_slider.setValue(new_zoom)
    
    def fit_to_page_clicked(self):
        self.fit_to_page = True
        self.fit_button.setChecked(True)
        if self.current_pdf_doc:
            self.display_pdf_page()
    
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.display_pdf_page()
    
    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_pdf_page()
    
    def prev_file(self):
        if self.current_file_index > 0:
            self.file_list.setCurrentRow(self.current_file_index - 1)
    
    def next_file(self):
        if self.current_file_index < len(self.pdf_files) - 1:
            self.file_list.setCurrentRow(self.current_file_index + 1)
    
    def clear_pdf_viewer(self):
        self.pdf_label.clear()
        self.pdf_label.setText("📄 No PDF loaded\n\nSelect a file from the list to preview")
        self.page_label.setText("Page: 0/0")
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        self.modify_button.setEnabled(False)
        self.next_file_button.setEnabled(False)
        self.prev_file_button.setEnabled(False)
        self.stats_label.setText("Select a file to view details")
        self.current_date_label.setText("No file selected")
        
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
            self.current_pdf_doc = None
        
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
            self.temp_pdf_path = None
    
    def modify_file_date(self):
        qt_datetime = self.date_time_edit.dateTime()
        new_date = datetime(
            qt_datetime.date().year(),
            qt_datetime.date().month(),
            qt_datetime.date().day(),
            qt_datetime.time().hour(),
            qt_datetime.time().minute(),
            qt_datetime.time().second()
        )
        
        self.statusBar().showMessage("🔄 Modifying file date...")
        
        self.modify_thread = DateModifyThread(
            self.nas_connection, 
            self.current_pdf_path, 
            new_date
        )
        self.modify_thread.success.connect(lambda: self.on_modify_success(new_date))
        self.modify_thread.error.connect(self.on_modify_error)
        self.modify_thread.start()
    
    def on_modify_success(self, new_date):
        # Update file info
        current_item = self.file_list.currentItem()
        if isinstance(current_item, FileListItem):
            current_item.file_info['modified'] = new_date
            current_item.update_display()
        
        self.current_date_label.setText(new_date.strftime('%Y-%m-%d %H:%M:%S'))
        self.statusBar().showMessage(f"✅ Date modified successfully to {new_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Auto-advance to next file after a short delay
        QTimer.singleShot(1000, self.next_file)
    
    def on_modify_error(self, error_msg):
        QMessageBox.critical(self, "Modification Error", f"Failed to modify date: {error_msg}")
        self.statusBar().showMessage("❌ Error modifying date")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set application metadata
    app.setApplicationName("PDF Date Modifier Pro")
    app.setOrganizationName("DateModifier")
    
    window = PDFViewerApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()