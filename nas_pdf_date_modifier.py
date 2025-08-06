#!/usr/bin/env python3
"""
NAS PDF Date Modifier
Connects to a NAS drive via SMB, allows browsing PDFs and modifying their dates.
"""

import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
import threading
from pathlib import Path

from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure
import fitz  # PyMuPDF
from PIL import Image, ImageTk


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


class PDFViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NAS PDF Date Modifier")
        self.root.geometry("1200x800")
        
        self.nas_connection = None
        self.pdf_files = []
        self.current_file_index = 0
        self.current_pdf_doc = None
        self.current_pdf_path = None
        self.temp_pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        
        self.setup_ui()
    
    def setup_ui(self):
        """Create the main user interface."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Connection frame
        connection_frame = ttk.LabelFrame(main_frame, text="NAS Connection", padding="10")
        connection_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Connection fields
        ttk.Label(connection_frame, text="NAS IP:").grid(row=0, column=0, sticky=tk.W)
        self.nas_ip_var = tk.StringVar()
        ttk.Entry(connection_frame, textvariable=self.nas_ip_var, width=20).grid(row=0, column=1, padx=5)
        
        ttk.Label(connection_frame, text="Username:").grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        self.username_var = tk.StringVar()
        ttk.Entry(connection_frame, textvariable=self.username_var, width=20).grid(row=0, column=3, padx=5)
        
        ttk.Label(connection_frame, text="Password:").grid(row=0, column=4, sticky=tk.W, padx=(10, 0))
        self.password_var = tk.StringVar()
        ttk.Entry(connection_frame, textvariable=self.password_var, show="*", width=20).grid(row=0, column=5, padx=5)
        
        ttk.Label(connection_frame, text="Share:").grid(row=1, column=0, sticky=tk.W)
        self.share_var = tk.StringVar()
        ttk.Entry(connection_frame, textvariable=self.share_var, width=20).grid(row=1, column=1, padx=5)
        
        ttk.Label(connection_frame, text="Path:").grid(row=1, column=2, sticky=tk.W, padx=(10, 0))
        self.path_var = tk.StringVar()
        ttk.Entry(connection_frame, textvariable=self.path_var, width=40).grid(row=1, column=3, columnspan=2, padx=5)
        
        self.connect_button = ttk.Button(connection_frame, text="Connect", command=self.connect_to_nas)
        self.connect_button.grid(row=1, column=5, padx=(10, 0))
        
        # File list frame
        file_frame = ttk.LabelFrame(main_frame, text="PDF Files", padding="10")
        file_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        
        # File listbox with scrollbar
        list_scroll = ttk.Scrollbar(file_frame)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_listbox = tk.Listbox(file_frame, yscrollcommand=list_scroll.set, width=40, height=20)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.config(command=self.file_listbox.yview)
        
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        
        # PDF viewer frame
        viewer_frame = ttk.LabelFrame(main_frame, text="PDF Preview", padding="10")
        viewer_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Navigation controls
        nav_frame = ttk.Frame(viewer_frame)
        nav_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.prev_page_btn = ttk.Button(nav_frame, text="← Previous", command=self.prev_page, state=tk.DISABLED)
        self.prev_page_btn.pack(side=tk.LEFT)
        
        self.page_label = ttk.Label(nav_frame, text="Page: 0/0")
        self.page_label.pack(side=tk.LEFT, padx=20)
        
        self.next_page_btn = ttk.Button(nav_frame, text="Next →", command=self.next_page, state=tk.DISABLED)
        self.next_page_btn.pack(side=tk.LEFT)
        
        # PDF canvas with scrollbars
        canvas_frame = ttk.Frame(viewer_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.pdf_canvas = tk.Canvas(canvas_frame, bg="gray", 
                                    yscrollcommand=v_scroll.set,
                                    xscrollcommand=h_scroll.set)
        self.pdf_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        v_scroll.config(command=self.pdf_canvas.yview)
        h_scroll.config(command=self.pdf_canvas.xview)
        
        # Date modification frame
        date_frame = ttk.LabelFrame(main_frame, text="Date Modification", padding="10")
        date_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        ttk.Label(date_frame, text="Current Modified Date:").grid(row=0, column=0, sticky=tk.W)
        self.current_date_label = ttk.Label(date_frame, text="No file selected")
        self.current_date_label.grid(row=0, column=1, padx=10)
        
        ttk.Label(date_frame, text="New Date:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.new_date_var = tk.StringVar()
        self.new_date_entry = ttk.Entry(date_frame, textvariable=self.new_date_var, width=20)
        self.new_date_entry.grid(row=0, column=3, padx=10)
        
        ttk.Label(date_frame, text="(Format: YYYY-MM-DD HH:MM:SS)").grid(row=0, column=4, padx=5)
        
        self.modify_button = ttk.Button(date_frame, text="Modify Date", command=self.modify_file_date, state=tk.DISABLED)
        self.modify_button.grid(row=0, column=5, padx=10)
        
        self.next_file_button = ttk.Button(date_frame, text="Next File →", command=self.next_file, state=tk.DISABLED)
        self.next_file_button.grid(row=0, column=6)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready. Please connect to NAS.")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=3)
        main_frame.rowconfigure(1, weight=1)
    
    def connect_to_nas(self):
        """Connect to the NAS and list PDF files."""
        nas_ip = self.nas_ip_var.get()
        username = self.username_var.get()
        password = self.password_var.get()
        share = self.share_var.get()
        path = self.path_var.get()
        
        if not all([nas_ip, username, password, share]):
            messagebox.showerror("Error", "Please fill in all connection fields")
            return
        
        self.status_var.set("Connecting to NAS...")
        self.connect_button.config(state=tk.DISABLED)
        
        def connect_thread():
            try:
                self.nas_connection = NASConnection(nas_ip, username, password, share)
                self.nas_connection.connect()
                
                self.pdf_files = self.nas_connection.list_pdf_files(path or '/')
                
                self.root.after(0, self.on_connection_success)
            except Exception as e:
                self.root.after(0, lambda: self.on_connection_error(str(e)))
        
        threading.Thread(target=connect_thread, daemon=True).start()
    
    def on_connection_success(self):
        """Handle successful NAS connection."""
        self.status_var.set(f"Connected. Found {len(self.pdf_files)} PDF files.")
        self.connect_button.config(text="Disconnect", state=tk.NORMAL, command=self.disconnect_from_nas)
        
        # Populate file list
        self.file_listbox.delete(0, tk.END)
        for file_info in self.pdf_files:
            display_text = f"{file_info['filename']} ({file_info['modified'].strftime('%Y-%m-%d %H:%M')})"
            self.file_listbox.insert(tk.END, display_text)
        
        if self.pdf_files:
            self.file_listbox.selection_set(0)
            self.on_file_select(None)
    
    def on_connection_error(self, error_msg):
        """Handle NAS connection error."""
        self.status_var.set("Connection failed")
        self.connect_button.config(state=tk.NORMAL)
        messagebox.showerror("Connection Error", error_msg)
    
    def disconnect_from_nas(self):
        """Disconnect from NAS."""
        if self.nas_connection:
            self.nas_connection.disconnect()
            self.nas_connection = None
        
        self.file_listbox.delete(0, tk.END)
        self.pdf_files = []
        self.clear_pdf_viewer()
        self.connect_button.config(text="Connect", command=self.connect_to_nas)
        self.status_var.set("Disconnected from NAS")
    
    def on_file_select(self, event):
        """Handle file selection from list."""
        selection = self.file_listbox.curselection()
        if not selection:
            return
        
        self.current_file_index = selection[0]
        file_info = self.pdf_files[self.current_file_index]
        
        self.current_date_label.config(text=file_info['modified'].strftime('%Y-%m-%d %H:%M:%S'))
        self.new_date_var.set(file_info['modified'].strftime('%Y-%m-%d %H:%M:%S'))
        
        self.status_var.set(f"Loading {file_info['filename']}...")
        
        # Download and display PDF
        threading.Thread(target=self.load_pdf, args=(file_info,), daemon=True).start()
    
    def load_pdf(self, file_info):
        """Download and load PDF for viewing."""
        try:
            # Create temporary file
            self.temp_pdf_path = tempfile.mktemp(suffix='.pdf')
            self.current_pdf_path = file_info['path']
            
            # Download file
            self.nas_connection.download_file(file_info['path'], self.temp_pdf_path)
            
            # Load PDF
            self.current_pdf_doc = fitz.open(self.temp_pdf_path)
            self.total_pages = len(self.current_pdf_doc)
            self.current_page = 0
            
            self.root.after(0, self.display_pdf_page)
            self.root.after(0, lambda: self.status_var.set(f"Loaded {file_info['filename']}"))
            self.root.after(0, lambda: self.modify_button.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.next_file_button.config(state=tk.NORMAL))
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to load PDF: {str(e)}"))
            self.root.after(0, lambda: self.status_var.set("Error loading PDF"))
    
    def display_pdf_page(self):
        """Display current page of PDF."""
        if not self.current_pdf_doc:
            return
        
        try:
            # Get page
            page = self.current_pdf_doc[self.current_page]
            
            # Render page to image
            mat = fitz.Matrix(1.5, 1.5)  # Scale factor
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.pil_tobytes(format="PNG")
            
            # Convert to PIL Image
            from io import BytesIO
            img = Image.open(BytesIO(img_data))
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(img)
            
            # Clear canvas and display image
            self.pdf_canvas.delete("all")
            self.pdf_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            self.pdf_canvas.config(scrollregion=self.pdf_canvas.bbox("all"))
            
            # Keep reference to prevent garbage collection
            self.pdf_canvas.image = photo
            
            # Update page label
            self.page_label.config(text=f"Page: {self.current_page + 1}/{self.total_pages}")
            
            # Update navigation buttons
            self.prev_page_btn.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
            self.next_page_btn.config(state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to display page: {str(e)}")
    
    def prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.display_pdf_page()
    
    def next_page(self):
        """Go to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_pdf_page()
    
    def clear_pdf_viewer(self):
        """Clear the PDF viewer."""
        self.pdf_canvas.delete("all")
        self.page_label.config(text="Page: 0/0")
        self.prev_page_btn.config(state=tk.DISABLED)
        self.next_page_btn.config(state=tk.DISABLED)
        self.modify_button.config(state=tk.DISABLED)
        self.next_file_button.config(state=tk.DISABLED)
        
        if self.current_pdf_doc:
            self.current_pdf_doc.close()
            self.current_pdf_doc = None
        
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            os.remove(self.temp_pdf_path)
            self.temp_pdf_path = None
    
    def modify_file_date(self):
        """Modify the date of the current file."""
        new_date_str = self.new_date_var.get()
        
        try:
            # Parse the new date
            new_date = datetime.strptime(new_date_str, '%Y-%m-%d %H:%M:%S')
            
            # Modify the file on NAS
            self.status_var.set("Modifying file date...")
            
            def modify_thread():
                try:
                    self.nas_connection.set_file_times(self.current_pdf_path, new_date)
                    
                    # Update local file info
                    self.pdf_files[self.current_file_index]['modified'] = new_date
                    
                    # Update display
                    display_text = f"{self.pdf_files[self.current_file_index]['filename']} ({new_date.strftime('%Y-%m-%d %H:%M')})"
                    self.file_listbox.delete(self.current_file_index)
                    self.file_listbox.insert(self.current_file_index, display_text)
                    self.file_listbox.selection_set(self.current_file_index)
                    
                    self.root.after(0, lambda: self.current_date_label.config(text=new_date.strftime('%Y-%m-%d %H:%M:%S')))
                    self.root.after(0, lambda: self.status_var.set("Date modified successfully"))
                    self.root.after(0, lambda: messagebox.showinfo("Success", "File date modified successfully"))
                    
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to modify date: {str(e)}"))
                    self.root.after(0, lambda: self.status_var.set("Error modifying date"))
            
            threading.Thread(target=modify_thread, daemon=True).start()
            
        except ValueError:
            messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD HH:MM:SS")
    
    def next_file(self):
        """Move to the next file in the list."""
        if self.current_file_index < len(self.pdf_files) - 1:
            self.file_listbox.selection_clear(self.current_file_index)
            self.current_file_index += 1
            self.file_listbox.selection_set(self.current_file_index)
            self.file_listbox.see(self.current_file_index)
            self.on_file_select(None)
        else:
            messagebox.showinfo("Info", "This is the last file in the list")


def main():
    root = tk.Tk()
    app = PDFViewerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()