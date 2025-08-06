#!/usr/bin/env python3
"""
NAS PDF Date Modifier
Connects to a NAS drive via SMB, allows browsing PDFs and modifying their dates.
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QGroupBox,
    QSplitter, QMessageBox, QScrollArea, QGridLayout, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPalette

from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure
import fitz  # PyMuPDF


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
            # Convert datetime to timestamp
            timestamp = int(modified_time.timestamp())
            
            # SMB2 setPathInfo to update file times
            # Note: This requires SMB2/3 protocol support
            self.connection.setPathInfo(
                self.share_name,
                remote_path,
                last_write_time=timestamp
            )
            return True
        except Exception as e:
            # Alternative approach: download, modify locally, re-upload
            # This preserves the content but updates the modification time
            temp_path = tempfile.mktemp(suffix='.pdf')
            try:
                self.download_file(remote_path, temp_path)
                
                # Set local file time
                os.utime(temp_path, (timestamp, timestamp))
                
                # Re-upload the file
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
            self.nas_connection = NASConnection(
                self.nas_ip, self.username, self.password, self.share_name
            )
            self.nas_connection.connect()
            files = self.nas_connection.list_pdf_files(self.path or '/')
            self.success.emit(files)
        except Exception as e:
            self.error.emit(str(e))
    
    def get_connection(self):
        return self.nas_connection


class PDFLoadThread(QThread):
    loaded = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, nas_connection, file_info):
        super().__init__()
        self.nas_connection = nas_connection
        self.file_info = file_info
    
    def run(self):
        try:
            temp_path = tempfile.mktemp(suffix='.pdf')
            self.nas_connection.download_file(self.file_info['path'], temp_path)
            
            pdf_doc = fitz.open(temp_path)
            
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
        
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("NAS PDF Date Modifier")
        self.setGeometry(100, 100, 1200, 800)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Connection section
        connection_group = QGroupBox("NAS Connection")
        connection_layout = QGridLayout()
        
        connection_layout.addWidget(QLabel("NAS IP:"), 0, 0)
        self.nas_ip_input = QLineEdit()
        connection_layout.addWidget(self.nas_ip_input, 0, 1)
        
        connection_layout.addWidget(QLabel("Username:"), 0, 2)
        self.username_input = QLineEdit()
        connection_layout.addWidget(self.username_input, 0, 3)
        
        connection_layout.addWidget(QLabel("Password:"), 0, 4)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        connection_layout.addWidget(self.password_input, 0, 5)
        
        connection_layout.addWidget(QLabel("Share:"), 1, 0)
        self.share_input = QLineEdit()
        connection_layout.addWidget(self.share_input, 1, 1)
        
        connection_layout.addWidget(QLabel("Path:"), 1, 2)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Leave empty for root")
        connection_layout.addWidget(self.path_input, 1, 3, 1, 2)
        
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_to_nas)
        connection_layout.addWidget(self.connect_button, 1, 5)
        
        connection_group.setLayout(connection_layout)
        main_layout.addWidget(connection_group)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # File list
        file_group = QGroupBox("PDF Files")
        file_layout = QVBoxLayout()
        
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_select)
        file_layout.addWidget(self.file_list)
        
        file_group.setLayout(file_layout)
        splitter.addWidget(file_group)
        
        # PDF viewer
        viewer_group = QGroupBox("PDF Preview")
        viewer_layout = QVBoxLayout()
        
        # Navigation controls
        nav_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton("← Previous")
        self.prev_page_btn.clicked.connect(self.prev_page)
        self.prev_page_btn.setEnabled(False)
        nav_layout.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Page: 0/0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("Next →")
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)
        nav_layout.addWidget(self.next_page_btn)
        
        nav_layout.addStretch()
        viewer_layout.addLayout(nav_layout)
        
        # PDF display area
        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setWidgetResizable(True)
        self.pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.pdf_label = QLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setText("No PDF loaded")
        self.pdf_label.setStyleSheet("QLabel { background-color: #f0f0f0; }")
        self.pdf_scroll.setWidget(self.pdf_label)
        
        viewer_layout.addWidget(self.pdf_scroll)
        viewer_group.setLayout(viewer_layout)
        splitter.addWidget(viewer_group)
        
        # Set splitter proportions
        splitter.setSizes([400, 800])
        main_layout.addWidget(splitter)
        
        # Date modification section
        date_group = QGroupBox("Date Modification")
        date_layout = QHBoxLayout()
        
        date_layout.addWidget(QLabel("Current Modified Date:"))
        self.current_date_label = QLabel("No file selected")
        date_layout.addWidget(self.current_date_label)
        
        date_layout.addStretch()
        
        date_layout.addWidget(QLabel("New Date:"))
        self.new_date_input = QLineEdit()
        self.new_date_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS")
        date_layout.addWidget(self.new_date_input)
        
        self.modify_button = QPushButton("Modify Date")
        self.modify_button.clicked.connect(self.modify_file_date)
        self.modify_button.setEnabled(False)
        date_layout.addWidget(self.modify_button)
        
        self.next_file_button = QPushButton("Next File →")
        self.next_file_button.clicked.connect(self.next_file)
        self.next_file_button.setEnabled(False)
        date_layout.addWidget(self.next_file_button)
        
        date_group.setLayout(date_layout)
        main_layout.addWidget(date_group)
        
        # Status bar
        self.statusBar().showMessage("Ready. Please connect to NAS.")
    
    def connect_to_nas(self):
        nas_ip = self.nas_ip_input.text()
        username = self.username_input.text()
        password = self.password_input.text()
        share = self.share_input.text()
        path = self.path_input.text()
        
        if not all([nas_ip, username, password, share]):
            QMessageBox.critical(self, "Error", "Please fill in all connection fields")
            return
        
        self.statusBar().showMessage("Connecting to NAS...")
        self.connect_button.setEnabled(False)
        
        self.connection_thread = ConnectionThread(nas_ip, username, password, share, path)
        self.connection_thread.success.connect(self.on_connection_success)
        self.connection_thread.error.connect(self.on_connection_error)
        self.connection_thread.start()
    
    def on_connection_success(self, files):
        self.nas_connection = self.connection_thread.get_connection()
        self.pdf_files = files
        
        self.statusBar().showMessage(f"Connected. Found {len(files)} PDF files.")
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self.connect_button.clicked.disconnect()
        self.connect_button.clicked.connect(self.disconnect_from_nas)
        
        # Populate file list
        self.file_list.clear()
        for file_info in files:
            display_text = f"{file_info['filename']} ({file_info['modified'].strftime('%Y-%m-%d %H:%M')})"
            self.file_list.addItem(display_text)
        
        if files:
            self.file_list.setCurrentRow(0)
    
    def on_connection_error(self, error_msg):
        self.statusBar().showMessage("Connection failed")
        self.connect_button.setEnabled(True)
        QMessageBox.critical(self, "Connection Error", error_msg)
    
    def disconnect_from_nas(self):
        if self.nas_connection:
            self.nas_connection.disconnect()
            self.nas_connection = None
        
        self.file_list.clear()
        self.pdf_files = []
        self.clear_pdf_viewer()
        
        self.connect_button.setText("Connect")
        self.connect_button.clicked.disconnect()
        self.connect_button.clicked.connect(self.connect_to_nas)
        
        self.statusBar().showMessage("Disconnected from NAS")
    
    def on_file_select(self):
        current_item = self.file_list.currentItem()
        if not current_item:
            return
        
        self.current_file_index = self.file_list.currentRow()
        file_info = self.pdf_files[self.current_file_index]
        
        self.current_date_label.setText(file_info['modified'].strftime('%Y-%m-%d %H:%M:%S'))
        self.new_date_input.setText(file_info['modified'].strftime('%Y-%m-%d %H:%M:%S'))
        
        self.statusBar().showMessage(f"Loading {file_info['filename']}...")
        
        # Load PDF in background
        self.pdf_thread = PDFLoadThread(self.nas_connection, file_info)
        self.pdf_thread.loaded.connect(self.on_pdf_loaded)
        self.pdf_thread.error.connect(self.on_pdf_error)
        self.pdf_thread.start()
    
    def on_pdf_loaded(self, data):
        # Clean up previous PDF if exists
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
        
        self.current_pdf_doc = data['doc']
        self.temp_pdf_path = data['temp_path']
        self.current_pdf_path = data['file_info']['path']
        self.total_pages = len(self.current_pdf_doc)
        self.current_page = 0
        
        self.display_pdf_page()
        
        self.statusBar().showMessage(f"Loaded {data['file_info']['filename']}")
        self.modify_button.setEnabled(True)
        self.next_file_button.setEnabled(True)
    
    def on_pdf_error(self, error_msg):
        QMessageBox.critical(self, "Error", f"Failed to load PDF: {error_msg}")
        self.statusBar().showMessage("Error loading PDF")
    
    def display_pdf_page(self):
        if not self.current_pdf_doc:
            return
        
        try:
            # Get page
            page = self.current_pdf_doc[self.current_page]
            
            # Render page to image
            mat = fitz.Matrix(1.5, 1.5)  # Scale factor
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to QImage
            img_data = pix.tobytes("ppm")
            qimg = QImage.fromData(img_data)
            
            # Convert to QPixmap and display
            pixmap = QPixmap.fromImage(qimg)
            self.pdf_label.setPixmap(pixmap)
            
            # Update page label
            self.page_label.setText(f"Page: {self.current_page + 1}/{self.total_pages}")
            
            # Update navigation buttons
            self.prev_page_btn.setEnabled(self.current_page > 0)
            self.next_page_btn.setEnabled(self.current_page < self.total_pages - 1)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to display page: {str(e)}")
    
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.display_pdf_page()
    
    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_pdf_page()
    
    def clear_pdf_viewer(self):
        self.pdf_label.clear()
        self.pdf_label.setText("No PDF loaded")
        self.page_label.setText("Page: 0/0")
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        self.modify_button.setEnabled(False)
        self.next_file_button.setEnabled(False)
        
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
            self.current_pdf_doc = None
        
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
            self.temp_pdf_path = None
    
    def modify_file_date(self):
        new_date_str = self.new_date_input.text()
        
        try:
            # Parse the new date
            new_date = datetime.strptime(new_date_str, '%Y-%m-%d %H:%M:%S')
            
            self.statusBar().showMessage("Modifying file date...")
            
            # Modify in background
            self.modify_thread = DateModifyThread(
                self.nas_connection, 
                self.current_pdf_path, 
                new_date
            )
            self.modify_thread.success.connect(lambda: self.on_modify_success(new_date))
            self.modify_thread.error.connect(self.on_modify_error)
            self.modify_thread.start()
            
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid date format. Use YYYY-MM-DD HH:MM:SS")
    
    def on_modify_success(self, new_date):
        # Update local file info
        self.pdf_files[self.current_file_index]['modified'] = new_date
        
        # Update display
        display_text = f"{self.pdf_files[self.current_file_index]['filename']} ({new_date.strftime('%Y-%m-%d %H:%M')})"
        self.file_list.item(self.current_file_index).setText(display_text)
        
        self.current_date_label.setText(new_date.strftime('%Y-%m-%d %H:%M:%S'))
        self.statusBar().showMessage("Date modified successfully")
        QMessageBox.information(self, "Success", "File date modified successfully")
    
    def on_modify_error(self, error_msg):
        QMessageBox.critical(self, "Error", f"Failed to modify date: {error_msg}")
        self.statusBar().showMessage("Error modifying date")
    
    def next_file(self):
        if self.current_file_index < len(self.pdf_files) - 1:
            self.file_list.setCurrentRow(self.current_file_index + 1)
        else:
            QMessageBox.information(self, "Info", "This is the last file in the list")


def main():
    app = QApplication(sys.argv)
    window = PDFViewerApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()