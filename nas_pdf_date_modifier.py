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
    QAbstractItemView, QStyle, QStyleOptionSlider, QToolBar, QFormLayout
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
        """Set the modification time of a file on the NAS using touch command."""
        if not self.connection:
            raise Exception("Not connected to NAS")
        
        import subprocess
        import fitz
        
        # Create temporary file
        temp_path = tempfile.mktemp(suffix='.pdf')
        
        try:
            # Download the original file from NAS
            self.download_file(remote_path, temp_path)
            
            # Update PDF internal metadata (optional but good to have)
            try:
                pdf_doc = fitz.open(temp_path)
                metadata = pdf_doc.metadata or {}
                
                # Format date for PDF metadata (D:YYYYMMDDHHmmSS)
                pdf_date = modified_time.strftime("D:%Y%m%d%H%M%S")
                metadata['modDate'] = pdf_date
                metadata['creationDate'] = pdf_date
                
                pdf_doc.set_metadata(metadata)
                
                # Save to a new temp file
                temp_modified = tempfile.mktemp(suffix='_meta.pdf')
                pdf_doc.save(temp_modified)
                pdf_doc.close()
                
                # Replace original temp with metadata-updated version
                os.replace(temp_modified, temp_path)
            except Exception as e:
                # If PDF metadata update fails, continue with original file
                print(f"Warning: Could not update PDF metadata: {e}")
            
            # Use touch command to set the file's modification time
            # Format: YYYYMMDDhhmm.ss
            touch_time = modified_time.strftime("%Y%m%d%H%M.%S")
            
            # Run touch command (format: YYYYMMDDhhmm)
            touch_time_formatted = modified_time.strftime("%Y%m%d%H%M")
            touch_cmd = ['touch', '-t', touch_time_formatted, temp_path]
            result = subprocess.run(touch_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"Touch command failed: {result.stderr}")
            
            # Verify the date was set correctly
            import stat
            file_stat = os.stat(temp_path)
            actual_mtime = datetime.fromtimestamp(file_stat.st_mtime)
            expected_mtime = modified_time.replace(second=0, microsecond=0)
            
            if abs((actual_mtime - expected_mtime).total_seconds()) > 60:
                print(f"Warning: Date might not be set correctly. Expected: {expected_mtime}, Got: {actual_mtime}")
            
            # Also set creation time on macOS using SetFile if available
            try:
                # Format for SetFile: MM/DD/YYYY HH:MM:SS
                setfile_time = modified_time.strftime("%m/%d/%Y %H:%M:%S")
                setfile_cmd = ['SetFile', '-d', setfile_time, '-m', setfile_time, temp_path]
                subprocess.run(setfile_cmd, capture_output=True, text=True)
            except:
                # SetFile might not be available, that's okay
                pass
            
            # Delete the original file on NAS
            try:
                self.connection.deleteFiles(self.share_name, remote_path)
            except:
                pass  # File might not exist
            
            # Upload the modified file back to NAS
            with open(temp_path, 'rb') as local_file:
                self.connection.storeFile(
                    self.share_name,
                    remote_path,
                    local_file
                )
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to modify file date: {str(e)}")
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass


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
        self._is_running = True
    
    def run(self):
        try:
            if not self._is_running:
                return
                
            self.progress.emit(25)
            temp_path = tempfile.mktemp(suffix='.pdf')
            
            if not self._is_running:
                return
                
            self.progress.emit(50)
            self.nas_connection.download_file(self.file_info['path'], temp_path)
            
            if not self._is_running:
                # Clean up temp file if thread was stopped
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                return
                
            self.progress.emit(75)
            pdf_doc = fitz.open(temp_path)
            
            if not self._is_running:
                # Clean up if thread was stopped
                pdf_doc.close()
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                return
                
            self.progress.emit(100)
            self.loaded.emit({
                'doc': pdf_doc,
                'temp_path': temp_path,
                'file_info': self.file_info
            })
        except Exception as e:
            self.error.emit(str(e))
            # Clean up on error
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
    
    def quit(self):
        """Override quit to set running flag."""
        self._is_running = False
        super().quit()


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
        
        # Keep thread references to prevent early destruction
        self.connection_thread = None
        self.pdf_thread = None
        self.modify_thread = None
        
        self.init_ui()
        self.setup_shortcuts()
        self.load_defaults()
    
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
        self.setWindowTitle("PDF Date Modifier")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget with main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Connection panel
        connection_group = QGroupBox("Network Connection")
        connection_layout = QFormLayout()
        connection_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        connection_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        
        # First row - server details
        server_row = QHBoxLayout()
        self.nas_ip_input = QLineEdit()
        self.nas_ip_input.setPlaceholderText("192.168.1.100")
        server_row.addWidget(self.nas_ip_input)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        server_row.addWidget(self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Password")
        server_row.addWidget(self.password_input)
        
        connection_layout.addRow("Server Details:", server_row)
        
        # Second row - share and path
        path_row = QHBoxLayout()
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("Share name")
        path_row.addWidget(self.share_input)
        
        self.base_path_input = QLineEdit()
        self.base_path_input.setPlaceholderText("/path/to/pdfs")
        path_row.addWidget(self.base_path_input)
        
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Subfolder (optional)")
        path_row.addWidget(self.folder_input)
        
        connection_layout.addRow("Path:", path_row)
        
        # Connection button and status
        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_to_nas)
        button_row.addWidget(self.connect_button)
        
        self.refresh_button = QPushButton("Refresh Files")
        self.refresh_button.clicked.connect(lambda: self.refresh_file_list(self.current_file_index))
        self.refresh_button.setEnabled(False)
        button_row.addWidget(self.refresh_button)
        
        self.connection_status_label = QLabel("Disconnected")
        button_row.addWidget(self.connection_status_label)
        button_row.addStretch()
        
        connection_layout.addRow("", button_row)
        
        connection_group.setLayout(connection_layout)
        connection_group.setMaximumHeight(150)
        main_layout.addWidget(connection_group)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - File list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        file_list_label = QLabel("PDF Files")
        file_list_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(file_list_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search files...")
        self.search_input.textChanged.connect(self.filter_files)
        left_layout.addWidget(self.search_input)
        
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.itemSelectionChanged.connect(self.on_file_select)
        left_layout.addWidget(self.file_list)
        
        self.file_count_label = QLabel("0 files")
        left_layout.addWidget(self.file_count_label)
        
        left_panel.setMaximumWidth(400)
        splitter.addWidget(left_panel)
        
        # Right panel - PDF viewer and controls
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # PDF viewer controls
        viewer_controls = QHBoxLayout()
        
        # Page navigation
        self.prev_page_btn = QPushButton("◀")
        self.prev_page_btn.clicked.connect(self.prev_page)
        self.prev_page_btn.setEnabled(False)
        self.prev_page_btn.setMaximumWidth(40)
        viewer_controls.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Page: 0/0")
        self.page_label.setMinimumWidth(100)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        viewer_controls.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("▶")
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)
        self.next_page_btn.setMaximumWidth(40)
        viewer_controls.addWidget(self.next_page_btn)
        
        viewer_controls.addStretch()
        
        # Zoom controls
        viewer_controls.addWidget(QLabel("Zoom:"))
        
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_out_btn.setMaximumWidth(30)
        viewer_controls.addWidget(self.zoom_out_btn)
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(25)
        self.zoom_slider.setMaximum(400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(150)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        viewer_controls.addWidget(self.zoom_slider)
        
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_in_btn.setMaximumWidth(30)
        viewer_controls.addWidget(self.zoom_in_btn)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(50)
        viewer_controls.addWidget(self.zoom_label)
        
        self.fit_button = QPushButton("Fit to Page")
        self.fit_button.clicked.connect(self.fit_to_page_clicked)
        self.fit_button.setCheckable(True)
        self.fit_button.setChecked(True)
        viewer_controls.addWidget(self.fit_button)
        
        right_layout.addLayout(viewer_controls)
        
        # PDF display area
        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setWidgetResizable(False)
        self.pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_scroll.setStyleSheet("QScrollArea { background-color: #525659; }")
        
        self.pdf_label = QLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setText("No PDF loaded")
        self.pdf_label.setStyleSheet("QLabel { background-color: white; padding: 20px; }")
        self.pdf_scroll.setWidget(self.pdf_label)
        
        right_layout.addWidget(self.pdf_scroll)
        
        # Progress bar
        self.load_progress = QProgressBar()
        self.load_progress.setMaximumHeight(5)
        self.load_progress.setTextVisible(False)
        self.load_progress.hide()
        right_layout.addWidget(self.load_progress)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 1050])
        
        main_layout.addWidget(splitter)
        
        # Bottom panel - Date modification controls
        date_group = QGroupBox("Date Modification")
        date_layout = QHBoxLayout()
        
        # Current date display
        date_layout.addWidget(QLabel("Current Date:"))
        self.current_date_label = QLabel("No file selected")
        self.current_date_label.setStyleSheet("font-weight: bold; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        date_layout.addWidget(self.current_date_label)
        
        date_layout.addStretch()
        
        # New date selection
        date_layout.addWidget(QLabel("New Date:"))
        self.date_time_edit = QDateTimeEdit()
        self.date_time_edit.setCalendarPopup(True)
        self.date_time_edit.setDateTime(QDateTime.currentDateTime())
        self.date_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.date_time_edit.setMinimumWidth(200)
        date_layout.addWidget(self.date_time_edit)
        
        self.today_btn = QPushButton("Set to Today")
        self.today_btn.clicked.connect(lambda: self.date_time_edit.setDateTime(QDateTime.currentDateTime()))
        date_layout.addWidget(self.today_btn)
        
        # Modification button
        self.modify_button = QPushButton("Apply Date Change")
        self.modify_button.clicked.connect(self.modify_file_date)
        self.modify_button.setEnabled(False)
        self.modify_button.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; padding: 5px 15px; } QPushButton:disabled { background-color: #cccccc; }")
        date_layout.addWidget(self.modify_button)
        
        # File navigation
        date_layout.addWidget(QLabel("  |  "))
        
        self.prev_file_button = QPushButton("← Previous File")
        self.prev_file_button.clicked.connect(self.prev_file)
        self.prev_file_button.setEnabled(False)
        date_layout.addWidget(self.prev_file_button)
        
        self.next_file_button = QPushButton("Next File →")
        self.next_file_button.clicked.connect(self.next_file)
        self.next_file_button.setEnabled(False)
        date_layout.addWidget(self.next_file_button)
        
        date_group.setLayout(date_layout)
        date_group.setMaximumHeight(100)
        main_layout.addWidget(date_group)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def filter_files(self, text):
        """Filter the file list based on search input."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())
    
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
                               "Please fill in Server IP, Username, Password, and Share fields.")
            return
        
        self.statusBar().showMessage(f"Connecting to {nas_ip}...")
        self.connect_button.setEnabled(False)
        
        # Clean up any existing thread
        if self.connection_thread and self.connection_thread.isRunning():
            self.connection_thread.wait()
        
        self.connection_thread = ConnectionThread(nas_ip, username, password, share, full_path)
        self.connection_thread.success.connect(self.on_connection_success)
        self.connection_thread.error.connect(self.on_connection_error)
        self.connection_thread.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self.connection_thread.finished.connect(self.connection_thread.deleteLater)
        self.connection_thread.start()
    
    def on_connection_success(self, files):
        self.nas_connection = self.connection_thread.get_connection()
        self.pdf_files = files
        self.connection_status = True
        
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.connection_status_label.setText("Connected")
        self.connection_status_label.setStyleSheet("color: green; font-weight: bold;")
        
        # Update file list
        self.file_list.clear()
        for file_info in files:
            item = FileListItem(file_info)
            self.file_list.addItem(item)
        
        self.file_count_label.setText(f"{len(files)} files")
        self.statusBar().showMessage(f"Connected - Found {len(files)} PDF files")
        
        if files:
            self.file_list.setCurrentRow(0)
    
    def on_connection_error(self, error_msg):
        self.statusBar().showMessage(f"Connection failed: {error_msg}")
        self.connect_button.setEnabled(True)
        QMessageBox.critical(self, "Connection Error", error_msg)
    
    def disconnect_from_nas(self):
        if self.nas_connection:
            self.nas_connection.disconnect()
            self.nas_connection = None
        
        self.connection_status = False
        self.connect_button.setText("Connect")
        self.refresh_button.setEnabled(False)
        self.connection_status_label.setText("Disconnected")
        self.connection_status_label.setStyleSheet("color: red;")
        
        self.file_list.clear()
        self.pdf_files = []
        self.file_count_label.setText("0 files")
        self.clear_pdf_viewer()
        
        self.statusBar().showMessage("Disconnected from NAS")
    
    def on_file_select(self):
        current_item = self.file_list.currentItem()
        if not current_item or not isinstance(current_item, FileListItem):
            return
        
        self.current_file_index = self.file_list.currentRow()
        file_info = current_item.file_info
        
        # Update dates
        modified_date = file_info['modified']
        self.current_date_label.setText(modified_date.strftime('%Y-%m-%d %H:%M:%S'))
        
        qt_datetime = QDateTime(
            QDate(modified_date.year, modified_date.month, modified_date.day),
            QTime(modified_date.hour, modified_date.minute, modified_date.second)
        )
        self.date_time_edit.setDateTime(qt_datetime)
        
        self.statusBar().showMessage(f"Loading {file_info['filename']}...")
        
        # Show progress bar
        self.load_progress.show()
        self.load_progress.setValue(0)
        
        # Load PDF
        # Clean up any existing thread - properly terminate if running
        if self.pdf_thread and self.pdf_thread.isRunning():
            # Disconnect signals to prevent callbacks from old thread
            try:
                self.pdf_thread.loaded.disconnect()
                self.pdf_thread.error.disconnect()
                self.pdf_thread.progress.disconnect()
            except:
                pass
            
            # Request thread to quit and wait briefly
            self.pdf_thread.quit()
            if not self.pdf_thread.wait(500):  # Wait max 500ms
                self.pdf_thread.terminate()  # Force terminate if still running
                self.pdf_thread.wait()
            
        self.pdf_thread = PDFLoadThread(self.nas_connection, file_info)
        self.pdf_thread.loaded.connect(self.on_pdf_loaded)
        self.pdf_thread.error.connect(self.on_pdf_error)
        self.pdf_thread.progress.connect(self.load_progress.setValue)
        self.pdf_thread.finished.connect(self.pdf_thread.deleteLater)
        self.pdf_thread.start()
    
    def on_pdf_loaded(self, data):
        # Clean up previous PDF - add error handling
        if self.current_pdf_doc:
            try:
                self.current_pdf_doc.close()
            except:
                pass
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            try:
                os.remove(self.temp_pdf_path)
            except:
                pass
        
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
        
        self.statusBar().showMessage(f"Loaded {data['file_info']['filename']} ({self.total_pages} pages)")
        self.modify_button.setEnabled(True)
        self.next_file_button.setEnabled(self.current_file_index < len(self.pdf_files) - 1)
        self.prev_file_button.setEnabled(self.current_file_index > 0)
    
    def on_pdf_error(self, error_msg):
        self.load_progress.hide()
        QMessageBox.critical(self, "Error", f"Failed to load PDF: {error_msg}")
        self.statusBar().showMessage("Error loading PDF")
    
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
        self.pdf_label.setText("No PDF loaded")
        self.page_label.setText("Page: 0/0")
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        self.modify_button.setEnabled(False)
        self.next_file_button.setEnabled(False)
        self.prev_file_button.setEnabled(False)
        self.current_date_label.setText("No file selected")
        
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
            self.current_pdf_doc = None
        
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
            self.temp_pdf_path = None
    
    def modify_file_date(self):
        if not self.current_pdf_path:
            return
        
        # Disable the modify button to prevent multiple operations
        self.modify_button.setEnabled(False)
            
        qt_datetime = self.date_time_edit.dateTime()
        new_date = datetime(
            qt_datetime.date().year(),
            qt_datetime.date().month(),
            qt_datetime.date().day(),
            qt_datetime.time().hour(),
            qt_datetime.time().minute(),
            qt_datetime.time().second()
        )
        
        self.statusBar().showMessage("Modifying file date...")
        
        # Clean up any existing thread
        if self.modify_thread and self.modify_thread.isRunning():
            self.modify_thread.wait()
        
        self.modify_thread = DateModifyThread(
            self.nas_connection, 
            self.current_pdf_path, 
            new_date
        )
        self.modify_thread.success.connect(lambda: self.on_modify_success(new_date))
        self.modify_thread.error.connect(self.on_modify_error)
        self.modify_thread.finished.connect(lambda: self.modify_button.setEnabled(True))
        self.modify_thread.finished.connect(self.modify_thread.deleteLater)
        self.modify_thread.start()
    
    def on_modify_success(self, new_date):
        # Update file info
        current_item = self.file_list.currentItem()
        current_index = self.current_file_index
        
        if isinstance(current_item, FileListItem):
            current_item.file_info['modified'] = new_date
            current_item.update_display()
        
        self.current_date_label.setText(new_date.strftime('%Y-%m-%d %H:%M:%S'))
        self.statusBar().showMessage(f"Date modified successfully to {new_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Refresh the file list to verify the change
        self.refresh_file_list(current_index)
        
        # Auto-advance to next file after a short delay
        QTimer.singleShot(1500, self.next_file)
    
    def refresh_file_list(self, maintain_index=None):
        """Refresh the file list from the NAS to show actual dates."""
        if not self.nas_connection:
            return
            
        try:
            # Get the current path
            base_path = self.base_path_input.text()
            folder = self.folder_input.text()
            
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
            
            # Reload files from NAS
            files = self.nas_connection.list_pdf_files(full_path)
            self.pdf_files = files
            
            # Update the list widget
            self.file_list.clear()
            for file_info in files:
                item = FileListItem(file_info)
                self.file_list.addItem(item)
            
            # Restore selection if needed
            if maintain_index is not None and maintain_index < len(files):
                self.file_list.setCurrentRow(maintain_index)
                
        except Exception as e:
            print(f"Error refreshing file list: {e}")
    
    def on_modify_error(self, error_msg):
        self.modify_button.setEnabled(True)  # Re-enable button on error
        QMessageBox.critical(self, "Modification Error", f"Failed to modify date: {error_msg}")
        self.statusBar().showMessage("Error modifying date")
    
    def closeEvent(self, event):
        """Properly clean up threads when closing the application."""
        # Wait for all threads to finish
        threads_to_wait = [
            self.connection_thread,
            self.pdf_thread, 
            self.modify_thread
        ]
        
        for thread in threads_to_wait:
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(1000)  # Wait up to 1 second
                if thread.isRunning():
                    thread.terminate()  # Force terminate if still running
                    thread.wait()
        
        # Disconnect from NAS if connected
        if self.nas_connection:
            try:
                self.nas_connection.disconnect()
            except:
                pass
        
        # Clean up temporary PDF file
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            try:
                os.remove(self.temp_pdf_path)
            except:
                pass
        
        # Close PDF document
        if self.current_pdf_doc:
            try:
                self.current_pdf_doc.close()
            except:
                pass
        
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set application metadata
    app.setApplicationName("PDF Date Modifier")
    app.setOrganizationName("DateModifier")
    
    window = PDFViewerApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()