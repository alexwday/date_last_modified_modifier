#!/usr/bin/env python3
"""
PDF Date Modifier Application - Robust Version
A professional tool for modifying PDF file dates on network-attached storage.
"""

import sys
import os
import tempfile
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QGroupBox,
    QSplitter, QMessageBox, QScrollArea, QDateTimeEdit,
    QSlider, QProgressBar, QToolBar, QStatusBar, QMenu,
    QFileDialog
)
from PyQt6.QtCore import (
    Qt, QDateTime, QTimer, pyqtSignal, QThread
)
from PyQt6.QtGui import (
    QPixmap, QImage, QAction, QKeySequence
)

# Import core modules
from src.core import (
    initialize_logging, get_logger, LogManager,
    ConfigurationManager, ConnectionManager, ConnectionConfig,
    PDFProcessor, FileOperationsManager, DateModifier,
    ThreadManager, TaskPriority
)

# Import UI components
from src.ui.main_window import (
    FileListItem, ConnectionDialog, LogViewerDialog, StatisticsDialog
)


class PDFDateModifierApp(QMainWindow):
    """Main application window with comprehensive error handling and logging."""
    
    def __init__(self):
        super().__init__()
        
        # Initialize logging first
        self.log_manager = initialize_logging("pdf_date_modifier")
        self.logger = get_logger(__name__)
        
        self.logger.info("="*50)
        self.logger.info("PDF Date Modifier Application Starting")
        self.logger.info(f"Version: 2.0.0 (Robust Edition)")
        self.logger.info(f"Python: {sys.version}")
        self.logger.info("="*50)
        
        # Initialize configuration
        self.config_manager = ConfigurationManager()
        
        # Initialize thread manager
        self.thread_manager = ThreadManager(
            max_workers=self.config_manager.config.app.max_worker_threads
        )
        
        # Initialize processors
        self.pdf_processor = PDFProcessor()
        self.file_ops_manager = FileOperationsManager()
        
        # Connection manager (initialized on connect)
        self.connection_manager: Optional[ConnectionManager] = None
        
        # State variables
        self.current_files: List[Dict[str, Any]] = []
        self.current_file_index = -1
        self.current_pdf_path: Optional[Path] = None
        self.temp_pdf_path: Optional[Path] = None
        
        # Initialize UI
        self.init_ui()
        self.setup_shortcuts()
        self.setup_exception_handler()
        
        # Load saved window geometry
        self.load_window_state()
        
        self.logger.info("Application initialization complete")
    
    def setup_exception_handler(self):
        """Setup global exception handler."""
        
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            self.logger.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_traceback)
            )
            
            error_msg = f"An unexpected error occurred:\n\n"
            error_msg += f"{exc_type.__name__}: {exc_value}\n\n"
            error_msg += "Please check the logs for more details."
            
            QMessageBox.critical(self, "Critical Error", error_msg)
        
        sys.excepthook = handle_exception
    
    def init_ui(self):
        """Initialize the user interface."""
        
        self.setWindowTitle("PDF Date Modifier - Professional Edition")
        self.setGeometry(100, 100,
                        self.config_manager.config.app.window_width,
                        self.config_manager.config.app.window_height)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create toolbar
        self.create_toolbar()
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - File list
        left_panel = self.create_file_list_panel()
        splitter.addWidget(left_panel)
        
        # Right panel - PDF viewer
        right_panel = self.create_pdf_viewer_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([400, 1000])
        main_layout.addWidget(splitter)
        
        # Bottom panel - Date modification
        date_panel = self.create_date_panel()
        main_layout.addWidget(date_panel)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Progress bar in status bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(15)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Connection status label
        self.conn_status_label = QLabel("Disconnected")
        self.conn_status_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
        self.status_bar.addPermanentWidget(self.conn_status_label)
        
        self.update_status("Ready")
    
    def create_menu_bar(self):
        """Create application menu bar."""
        
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        connect_action = QAction("Connect to NAS", self)
        connect_action.setShortcut(QKeySequence("Ctrl+K"))
        connect_action.triggered.connect(self.show_connection_dialog)
        file_menu.addAction(connect_action)
        
        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self.disconnect)
        file_menu.addAction(disconnect_action)
        
        file_menu.addSeparator()
        
        export_config_action = QAction("Export Configuration", self)
        export_config_action.triggered.connect(self.export_configuration)
        file_menu.addAction(export_config_action)
        
        import_config_action = QAction("Import Configuration", self)
        import_config_action.triggered.connect(self.import_configuration)
        file_menu.addAction(import_config_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        logs_action = QAction("View Logs", self)
        logs_action.setShortcut(QKeySequence("Ctrl+L"))
        logs_action.triggered.connect(self.show_log_viewer)
        view_menu.addAction(logs_action)
        
        stats_action = QAction("Statistics", self)
        stats_action.triggered.connect(self.show_statistics)
        view_menu.addAction(stats_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        batch_action = QAction("Batch Process", self)
        batch_action.triggered.connect(self.batch_process)
        tools_menu.addAction(batch_action)
        
        validate_action = QAction("Validate All PDFs", self)
        validate_action.triggered.connect(self.validate_all_pdfs)
        tools_menu.addAction(validate_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_toolbar(self):
        """Create application toolbar."""
        
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Connect button
        connect_action = QAction("Connect", self)
        connect_action.triggered.connect(self.show_connection_dialog)
        toolbar.addAction(connect_action)
        
        # Refresh button
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_file_list)
        toolbar.addAction(refresh_action)
        
        toolbar.addSeparator()
        
        # Navigation buttons
        prev_file_action = QAction("Previous", self)
        prev_file_action.triggered.connect(self.select_previous_file)
        toolbar.addAction(prev_file_action)
        
        next_file_action = QAction("Next", self)
        next_file_action.triggered.connect(self.select_next_file)
        toolbar.addAction(next_file_action)
        
        toolbar.addSeparator()
        
        # Apply date button
        apply_action = QAction("Apply Date", self)
        apply_action.triggered.connect(self.apply_date_modification)
        toolbar.addAction(apply_action)
    
    def create_file_list_panel(self) -> QWidget:
        """Create the file list panel."""
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Title
        title = QLabel("PDF Files")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search files...")
        self.search_input.textChanged.connect(self.filter_files)
        layout.addWidget(self.search_input)
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        layout.addWidget(self.file_list)
        
        # File count label
        self.file_count_label = QLabel("0 files")
        layout.addWidget(self.file_count_label)
        
        panel.setMaximumWidth(450)
        return panel
    
    def create_pdf_viewer_panel(self) -> QWidget:
        """Create the PDF viewer panel."""
        
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Viewer controls
        controls = QHBoxLayout()
        
        # Page navigation
        self.prev_page_btn = QPushButton("◀")
        self.prev_page_btn.clicked.connect(self.previous_page)
        self.prev_page_btn.setEnabled(False)
        controls.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Page: 0/0")
        self.page_label.setMinimumWidth(100)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("▶")
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)
        controls.addWidget(self.next_page_btn)
        
        controls.addStretch()
        
        # Zoom controls
        controls.addWidget(QLabel("Zoom:"))
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(25)
        self.zoom_slider.setMaximum(400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(150)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        controls.addWidget(self.zoom_slider)
        
        self.zoom_label = QLabel("100%")
        controls.addWidget(self.zoom_label)
        
        layout.addLayout(controls)
        
        # PDF display area
        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setWidgetResizable(False)
        self.pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.pdf_label = QLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setText("No PDF loaded")
        self.pdf_label.setStyleSheet("QLabel { background-color: white; padding: 20px; }")
        self.pdf_scroll.setWidget(self.pdf_label)
        
        layout.addWidget(self.pdf_scroll)
        
        return panel
    
    def create_date_panel(self) -> QGroupBox:
        """Create the date modification panel."""
        
        group = QGroupBox("Date Modification")
        layout = QHBoxLayout()
        
        # Current date
        layout.addWidget(QLabel("Current:"))
        self.current_date_label = QLabel("No file selected")
        self.current_date_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.current_date_label)
        
        layout.addStretch()
        
        # New date
        layout.addWidget(QLabel("New Date:"))
        self.date_time_edit = QDateTimeEdit()
        self.date_time_edit.setCalendarPopup(True)
        self.date_time_edit.setDateTime(QDateTime.currentDateTime())
        self.date_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        layout.addWidget(self.date_time_edit)
        
        # Buttons
        self.today_btn = QPushButton("Today")
        self.today_btn.clicked.connect(lambda: self.date_time_edit.setDateTime(QDateTime.currentDateTime()))
        layout.addWidget(self.today_btn)
        
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply_date_modification)
        self.apply_btn.setEnabled(False)
        self.apply_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        layout.addWidget(self.apply_btn)
        
        group.setLayout(layout)
        group.setMaximumHeight(100)
        
        return group
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        
        shortcuts = [
            ("Right", self.next_page),
            ("Left", self.previous_page),
            ("Ctrl+Right", self.select_next_file),
            ("Ctrl+Left", self.select_previous_file),
            ("Ctrl++", self.zoom_in),
            ("Ctrl+-", self.zoom_out),
            ("Ctrl+0", self.zoom_reset),
            ("Ctrl+M", self.apply_date_modification),
            ("F5", self.refresh_file_list),
        ]
        
        for key, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(callback)
            self.addAction(action)
    
    def show_connection_dialog(self):
        """Show connection configuration dialog."""
        
        dialog = ConnectionDialog(self.config_manager, self)
        
        if dialog.exec():
            self.connect_to_nas()
    
    def connect_to_nas(self):
        """Connect to NAS server."""
        
        try:
            self.update_status("Connecting to NAS...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            
            # Create connection config
            config = ConnectionConfig(
                nas_ip=self.config_manager.config.server.nas_ip,
                username=self.config_manager.config.server.username,
                password=self.config_manager.config.server.password,
                share_name=self.config_manager.config.server.share_name,
                domain=self.config_manager.config.server.domain,
                port=self.config_manager.config.server.port,
                timeout=self.config_manager.config.server.timeout,
                max_retries=self.config_manager.config.app.retry_max_attempts,
                retry_delay=self.config_manager.config.app.retry_delay,
                retry_backoff=self.config_manager.config.app.retry_backoff
            )
            
            # Close existing connection
            if self.connection_manager:
                self.connection_manager.close()
            
            # Create new connection
            self.connection_manager = ConnectionManager(config)
            
            # Test connection
            if not self.connection_manager.test_connection():
                raise Exception("Connection test failed")
            
            # Update UI
            self.conn_status_label.setText("Connected")
            self.conn_status_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
            
            self.update_status(f"Connected to {config.nas_ip}")
            self.logger.info(f"Successfully connected to {config.nas_ip}")
            
            # Load file list
            self.load_file_list()
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            QMessageBox.critical(self, "Connection Error", str(e))
            self.update_status("Connection failed")
            
        finally:
            self.progress_bar.setVisible(False)
    
    def disconnect(self):
        """Disconnect from NAS."""
        
        if self.connection_manager:
            self.connection_manager.close()
            self.connection_manager = None
        
        self.conn_status_label.setText("Disconnected")
        self.conn_status_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
        
        self.file_list.clear()
        self.current_files = []
        self.file_count_label.setText("0 files")
        
        self.update_status("Disconnected")
        self.logger.info("Disconnected from NAS")
    
    def load_file_list(self):
        """Load PDF files from NAS."""
        
        if not self.connection_manager:
            return
        
        try:
            self.update_status("Loading file list...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            
            # Get base path and folder path
            base_path = self.config_manager.config.server.base_path or "/"
            folder_path = self.config_manager.config.server.folder_path if hasattr(self.config_manager.config.server, 'folder_path') else ""
            
            # Combine paths
            if folder_path:
                # Clean up paths - remove leading/trailing slashes from folder_path
                folder_path = folder_path.strip('/')
                if base_path.endswith('/'):
                    full_path = base_path + folder_path
                else:
                    full_path = base_path + '/' + folder_path
            else:
                full_path = base_path
            
            self.logger.info(f"Loading files from path: {full_path}")
            
            # Submit task to thread manager
            def load_task():
                return self.connection_manager.list_files(full_path, "*.pdf")
            
            future = self.thread_manager.submit_simple_task(load_task)
            files = future.result(timeout=30)
            
            # Update UI
            self.current_files = files
            self.file_list.clear()
            
            for file_info in files:
                item = FileListItem(file_info)
                self.file_list.addItem(item)
            
            self.file_count_label.setText(f"{len(files)} files")
            self.update_status(f"Loaded {len(files)} PDF files")
            
            self.logger.info(f"Loaded {len(files)} PDF files from NAS")
            
            # Select first file
            if files:
                self.file_list.setCurrentRow(0)
            
        except Exception as e:
            self.logger.error(f"Failed to load file list: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load files: {e}")
            
        finally:
            self.progress_bar.setVisible(False)
    
    def refresh_file_list(self):
        """Refresh the file list."""
        
        if self.connection_manager:
            self.load_file_list()
    
    def filter_files(self, text: str):
        """Filter file list based on search text."""
        
        search_text = text.lower()
        
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setHidden(search_text not in item.text().lower())
    
    def on_file_selected(self):
        """Handle file selection."""
        
        current_item = self.file_list.currentItem()
        
        if not current_item or not isinstance(current_item, FileListItem):
            return
        
        self.current_file_index = self.file_list.currentRow()
        file_info = current_item.file_info
        
        # Update date display
        self.current_date_label.setText(
            file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')
        )
        
        # Set new date to current date
        qt_datetime = QDateTime(
            file_info['modified'].year,
            file_info['modified'].month,
            file_info['modified'].day,
            file_info['modified'].hour,
            file_info['modified'].minute,
            file_info['modified'].second
        )
        self.date_time_edit.setDateTime(qt_datetime)
        
        # Load PDF preview
        self.load_pdf_preview(file_info)
        
        # Enable apply button
        self.apply_btn.setEnabled(True)
    
    def load_pdf_preview(self, file_info: Dict[str, Any]):
        """Load PDF preview in thread."""
        
        if not self.connection_manager:
            return
        
        try:
            self.update_status(f"Loading {file_info['filename']}...")
            
            # Clean up previous temp file
            if self.temp_pdf_path and self.temp_pdf_path.exists():
                try:
                    os.remove(self.temp_pdf_path)
                except:
                    pass
            
            # Download to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            self.temp_pdf_path = Path(temp_file.name)
            temp_file.close()
            
            # Submit download task
            def download_task():
                return self.connection_manager.download_file(
                    file_info['path'], 
                    str(self.temp_pdf_path)
                )
            
            self.thread_manager.submit_task(
                download_task,
                priority=TaskPriority.HIGH,
                callback=lambda _: self.display_pdf_preview(),
                error_callback=lambda e: self.pdf_load_error(e),
                task_name=f"Download {file_info['filename']}"
            )
            
            self.current_pdf_path = Path(file_info['path'])
            
        except Exception as e:
            self.logger.error(f"Failed to load PDF: {e}")
            self.pdf_load_error(e)
    
    def display_pdf_preview(self):
        """Display PDF preview."""
        
        if not self.temp_pdf_path or not self.temp_pdf_path.exists():
            return
        
        try:
            # Get preview image
            preview_bytes = self.pdf_processor.get_pdf_preview(
                self.temp_pdf_path,
                page_num=0,
                zoom=self.zoom_slider.value() / 100.0
            )
            
            if preview_bytes:
                # Convert to QPixmap
                image = QImage.fromData(preview_bytes)
                pixmap = QPixmap.fromImage(image)
                
                # Display
                self.pdf_label.setPixmap(pixmap)
                self.pdf_label.resize(pixmap.size())
                
                # Update page info
                info = self.pdf_processor.extract_pdf_info(self.temp_pdf_path)
                page_count = info.get('page_count', 0)
                self.page_label.setText(f"Page: 1/{page_count}")
                
                # Enable navigation if multiple pages
                self.prev_page_btn.setEnabled(False)
                self.next_page_btn.setEnabled(page_count > 1)
                
                self.update_status("PDF loaded successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to display PDF: {e}")
            self.pdf_load_error(e)
    
    def pdf_load_error(self, error):
        """Handle PDF load error."""
        
        self.pdf_label.setText(f"Error loading PDF:\n{error}")
        self.update_status("Error loading PDF")
    
    def apply_date_modification(self):
        """Apply date modification to current file."""
        
        if not self.connection_manager or not self.current_pdf_path:
            return
        
        try:
            # Get new date
            qt_datetime = self.date_time_edit.dateTime()
            new_date = datetime(
                qt_datetime.date().year(),
                qt_datetime.date().month(),
                qt_datetime.date().day(),
                qt_datetime.time().hour(),
                qt_datetime.time().minute(),
                qt_datetime.time().second()
            )
            
            self.update_status("Applying date modification...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 100)
            
            # Download file
            self.progress_bar.setValue(25)
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            self.connection_manager.download_file(str(self.current_pdf_path), str(temp_path))
            
            # Process PDF
            self.progress_bar.setValue(50)
            success, result = self.pdf_processor.process_pdf_with_date_change(
                temp_path, 
                new_date,
                update_metadata=self.config_manager.config.app.update_pdf_metadata
            )
            
            if not success:
                raise Exception(f"PDF processing failed: {result.get('errors', ['Unknown error'])}")
            
            # Modify file dates
            self.progress_bar.setValue(75)
            self.file_ops_manager.modify_pdf_dates(temp_path, new_date)
            
            # Upload back to NAS
            self.connection_manager.upload_file(str(temp_path), str(self.current_pdf_path))
            
            self.progress_bar.setValue(100)
            
            # Update UI
            current_item = self.file_list.currentItem()
            if isinstance(current_item, FileListItem):
                current_item.file_info['modified'] = new_date
                current_item.update_display()
            
            self.current_date_label.setText(new_date.strftime('%Y-%m-%d %H:%M:%S'))
            
            self.update_status(f"Date modified successfully")
            self.logger.info(f"Modified date for {self.current_pdf_path} to {new_date}")
            
            # Clean up temp file
            try:
                temp_path.unlink()
            except:
                pass
            
            # Auto-advance if enabled
            if self.config_manager.config.app.auto_advance:
                QTimer.singleShot(
                    self.config_manager.config.app.auto_advance_delay,
                    self.select_next_file
                )
            
        except Exception as e:
            self.logger.error(f"Date modification failed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to modify date: {e}")
            self.update_status("Date modification failed")
            
        finally:
            self.progress_bar.setVisible(False)
    
    def batch_process(self):
        """Batch process multiple files."""
        
        if not self.connection_manager or not self.current_files:
            QMessageBox.warning(self, "Warning", "Please connect and load files first.")
            return
        
        # Get new date
        qt_datetime = self.date_time_edit.dateTime()
        new_date = datetime(
            qt_datetime.date().year(),
            qt_datetime.date().month(),
            qt_datetime.date().day(),
            qt_datetime.time().hour(),
            qt_datetime.time().minute(),
            qt_datetime.time().second()
        )
        
        reply = QMessageBox.question(
            self, "Batch Process",
            f"Apply date {new_date.strftime('%Y-%m-%d %H:%M:%S')} to ALL {len(self.current_files)} files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.current_files))
        
        success_count = 0
        error_count = 0
        
        for i, file_info in enumerate(self.current_files):
            self.progress_bar.setValue(i)
            self.update_status(f"Processing {i+1}/{len(self.current_files)}: {file_info['filename']}")
            
            try:
                # Process each file
                temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                temp_path = Path(temp_file.name)
                temp_file.close()
                
                # Download
                self.connection_manager.download_file(file_info['path'], str(temp_path))
                
                # Process
                success, _ = self.pdf_processor.process_pdf_with_date_change(temp_path, new_date)
                
                if success:
                    # Modify dates
                    self.file_ops_manager.modify_pdf_dates(temp_path, new_date)
                    
                    # Upload
                    self.connection_manager.upload_file(str(temp_path), file_info['path'])
                    
                    success_count += 1
                else:
                    error_count += 1
                
                # Clean up
                try:
                    temp_path.unlink()
                except:
                    pass
                
            except Exception as e:
                self.logger.error(f"Failed to process {file_info['filename']}: {e}")
                error_count += 1
            
            # Allow UI to update
            QApplication.processEvents()
        
        self.progress_bar.setVisible(False)
        
        # Show results
        QMessageBox.information(
            self, "Batch Process Complete",
            f"Processed {len(self.current_files)} files:\n"
            f"Success: {success_count}\n"
            f"Errors: {error_count}"
        )
        
        # Refresh file list
        self.refresh_file_list()
    
    def validate_all_pdfs(self):
        """Validate all PDF files."""
        
        if not self.current_files:
            QMessageBox.warning(self, "Warning", "No files loaded.")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.current_files))
        
        invalid_files = []
        
        for i, file_info in enumerate(self.current_files):
            self.progress_bar.setValue(i)
            self.update_status(f"Validating {i+1}/{len(self.current_files)}: {file_info['filename']}")
            
            try:
                # Download to temp
                temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                temp_path = Path(temp_file.name)
                temp_file.close()
                
                self.connection_manager.download_file(file_info['path'], str(temp_path))
                
                # Validate
                is_valid, error, _ = self.pdf_processor.validator.validate_pdf(temp_path)
                
                if not is_valid:
                    invalid_files.append({
                        'filename': file_info['filename'],
                        'error': error
                    })
                
                # Clean up
                try:
                    temp_path.unlink()
                except:
                    pass
                
            except Exception as e:
                invalid_files.append({
                    'filename': file_info['filename'],
                    'error': str(e)
                })
            
            QApplication.processEvents()
        
        self.progress_bar.setVisible(False)
        
        # Show results
        if invalid_files:
            msg = f"Found {len(invalid_files)} invalid PDF files:\n\n"
            for file_info in invalid_files[:10]:  # Show first 10
                msg += f"• {file_info['filename']}: {file_info['error']}\n"
            
            if len(invalid_files) > 10:
                msg += f"\n... and {len(invalid_files) - 10} more"
            
            QMessageBox.warning(self, "Validation Results", msg)
        else:
            QMessageBox.information(self, "Validation Results", 
                                   f"All {len(self.current_files)} PDF files are valid!")
    
    def select_previous_file(self):
        """Select previous file in list."""
        
        if self.current_file_index > 0:
            self.file_list.setCurrentRow(self.current_file_index - 1)
    
    def select_next_file(self):
        """Select next file in list."""
        
        if self.current_file_index < len(self.current_files) - 1:
            self.file_list.setCurrentRow(self.current_file_index + 1)
    
    def previous_page(self):
        """Show previous PDF page."""
        # TODO: Implement multi-page navigation
        pass
    
    def next_page(self):
        """Show next PDF page."""
        # TODO: Implement multi-page navigation
        pass
    
    def on_zoom_changed(self, value: int):
        """Handle zoom change."""
        
        self.zoom_label.setText(f"{value}%")
        
        if self.temp_pdf_path and self.temp_pdf_path.exists():
            self.display_pdf_preview()
    
    def zoom_in(self):
        """Zoom in."""
        
        new_value = min(self.zoom_slider.value() + 25, 400)
        self.zoom_slider.setValue(new_value)
    
    def zoom_out(self):
        """Zoom out."""
        
        new_value = max(self.zoom_slider.value() - 25, 25)
        self.zoom_slider.setValue(new_value)
    
    def zoom_reset(self):
        """Reset zoom to 100%."""
        
        self.zoom_slider.setValue(100)
    
    def show_log_viewer(self):
        """Show log viewer dialog."""
        
        dialog = LogViewerDialog(self.log_manager, self)
        dialog.exec()
    
    def show_statistics(self):
        """Show statistics dialog."""
        
        dialog = StatisticsDialog(self.thread_manager, self.connection_manager, self)
        dialog.exec()
    
    def export_configuration(self):
        """Export configuration to file."""
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Configuration",
            "pdf_modifier_config.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            self.config_manager.export_config(Path(file_path))
            QMessageBox.information(self, "Success", "Configuration exported successfully.")
    
    def import_configuration(self):
        """Import configuration from file."""
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Configuration",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            self.config_manager.import_config(Path(file_path))
            QMessageBox.information(self, "Success", "Configuration imported successfully.")
    
    def show_about(self):
        """Show about dialog."""
        
        about_text = """
        <h2>PDF Date Modifier</h2>
        <p><b>Version 2.0.0 - Robust Edition</b></p>
        <p>A professional tool for modifying PDF file dates on network-attached storage.</p>
        <br>
        <p><b>Features:</b></p>
        <ul>
            <li>Comprehensive error handling and logging</li>
            <li>Connection pooling and retry logic</li>
            <li>Atomic file operations with rollback</li>
            <li>PDF validation and repair</li>
            <li>Batch processing support</li>
            <li>Thread management and monitoring</li>
        </ul>
        <br>
        <p>© 2024 - Professional Edition</p>
        """
        
        QMessageBox.about(self, "About PDF Date Modifier", about_text)
    
    def update_status(self, message: str):
        """Update status bar message."""
        
        self.status_bar.showMessage(message)
        self.logger.debug(f"Status: {message}")
    
    def load_window_state(self):
        """Load saved window state."""
        
        # TODO: Implement window state persistence
        pass
    
    def save_window_state(self):
        """Save window state."""
        
        # TODO: Implement window state persistence
        pass
    
    def closeEvent(self, event):
        """Handle application close event."""
        
        self.logger.info("Application shutting down...")
        
        # Save window state
        self.save_window_state()
        
        # Clean up
        try:
            # Close connection
            if self.connection_manager:
                self.connection_manager.close()
            
            # Clean up PDF processor
            self.pdf_processor.cleanup()
            
            # Clean up file operations
            self.file_ops_manager.cleanup()
            
            # Shutdown thread manager
            self.thread_manager.shutdown(timeout=5.0)
            
            # Clean up temp files
            if self.temp_pdf_path and self.temp_pdf_path.exists():
                try:
                    self.temp_pdf_path.unlink()
                except:
                    pass
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
        
        self.logger.info("Application shutdown complete")
        
        event.accept()


def main():
    """Main application entry point."""
    
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Date Modifier")
    app.setOrganizationName("PDFTools")
    app.setStyle('Fusion')
    
    # Create and show main window
    window = PDFDateModifierApp()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()