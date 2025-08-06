#!/usr/bin/env python3
"""
PDF processing with error recovery, metadata handling, and validation.
"""

import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import fitz  # PyMuPDF

from .logging_config import get_logger, log_exception
from .file_operations import AtomicFileOperation, FileValidator


class PDFProcessingError(Exception):
    """Custom exception for PDF processing failures."""
    pass


class PDFMetadata:
    """Handle PDF metadata operations."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
    
    def read_metadata(self, pdf_path: Path) -> Dict[str, Any]:
        """Read metadata from a PDF file."""
        try:
            with fitz.open(str(pdf_path)) as doc:
                metadata = doc.metadata or {}
                
                # Parse dates if present
                parsed_metadata = {}
                for key, value in metadata.items():
                    if value and key in ['creationDate', 'modDate']:
                        parsed_metadata[key] = self._parse_pdf_date(value)
                    else:
                        parsed_metadata[key] = value
                
                # Add document info
                parsed_metadata['page_count'] = len(doc)
                parsed_metadata['is_encrypted'] = doc.is_encrypted
                parsed_metadata['is_dirty'] = doc.is_dirty
                
                return parsed_metadata
                
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'read_metadata', 'file': str(pdf_path)})
            raise PDFProcessingError(f"Failed to read PDF metadata: {e}")
    
    def update_metadata(self, pdf_path: Path, metadata_updates: Dict[str, Any], 
                       output_path: Optional[Path] = None) -> Path:
        """Update PDF metadata."""
        
        output_path = output_path or pdf_path
        
        try:
            with AtomicFileOperation(output_path, "metadata_update") as temp_file:
                # Open and update PDF
                doc = fitz.open(str(pdf_path))
                
                try:
                    # Get existing metadata
                    current_metadata = doc.metadata or {}
                    
                    # Update with new values
                    for key, value in metadata_updates.items():
                        if value is not None:
                            if isinstance(value, datetime):
                                # Convert datetime to PDF format
                                current_metadata[key] = self._format_pdf_date(value)
                            else:
                                current_metadata[key] = str(value)
                    
                    # Set the updated metadata
                    doc.set_metadata(current_metadata)
                    
                    # Save to temp file
                    doc.save(str(temp_file))
                    
                    self.logger.info(f"Updated metadata for {pdf_path}")
                    
                finally:
                    doc.close()
                
                return output_path
                
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'update_metadata', 'file': str(pdf_path)})
            raise PDFProcessingError(f"Failed to update PDF metadata: {e}")
    
    def _parse_pdf_date(self, date_str: str) -> Optional[datetime]:
        """Parse PDF date format (D:YYYYMMDDHHmmSS)."""
        
        if not date_str:
            return None
        
        # Remove 'D:' prefix if present
        if date_str.startswith('D:'):
            date_str = date_str[2:]
        
        # Remove timezone info if present
        if '+' in date_str:
            date_str = date_str.split('+')[0]
        elif '-' in date_str and len(date_str) > 8:
            date_str = date_str.split('-')[0]
        
        try:
            # Try different formats
            for fmt in ['%Y%m%d%H%M%S', '%Y%m%d%H%M', '%Y%m%d']:
                try:
                    return datetime.strptime(date_str[:len(fmt.replace('%', ''))], fmt)
                except ValueError:
                    continue
                    
        except Exception as e:
            self.logger.warning(f"Failed to parse PDF date '{date_str}': {e}")
        
        return None
    
    def _format_pdf_date(self, dt: datetime) -> str:
        """Format datetime to PDF date format."""
        return f"D:{dt.strftime('%Y%m%d%H%M%S')}"


class PDFValidator:
    """Validate and repair PDF files."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.file_validator = FileValidator()
    
    def validate_pdf(self, pdf_path: Path) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Comprehensive PDF validation."""
        
        validation_results = {
            'is_valid': False,
            'has_header': False,
            'has_eof': False,
            'is_readable': False,
            'page_count': 0,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Check basic file structure
            is_valid, error = self.file_validator.verify_pdf(pdf_path)
            validation_results['has_header'] = is_valid
            
            if not is_valid:
                validation_results['errors'].append(error or "Invalid PDF header")
                return False, "Invalid PDF structure", validation_results
            
            # Try to open with PyMuPDF
            try:
                with fitz.open(str(pdf_path)) as doc:
                    validation_results['is_readable'] = True
                    validation_results['page_count'] = len(doc)
                    
                    # Check for corruption
                    if doc.is_dirty:
                        validation_results['warnings'].append("Document has unsaved changes")
                    
                    if doc.is_encrypted:
                        validation_results['warnings'].append("Document is encrypted")
                    
                    # Try to access all pages
                    for i, page in enumerate(doc):
                        try:
                            _ = page.get_text()
                        except Exception as e:
                            validation_results['warnings'].append(f"Page {i+1} may be corrupted: {e}")
                    
                    validation_results['is_valid'] = True
                    
            except Exception as e:
                validation_results['errors'].append(f"PyMuPDF error: {e}")
                return False, f"PDF is not readable: {e}", validation_results
            
            # Check for EOF marker
            with open(pdf_path, 'rb') as f:
                f.seek(-128, 2)  # Seek to end
                tail = f.read()
                validation_results['has_eof'] = b'%%EOF' in tail
                
                if not validation_results['has_eof']:
                    validation_results['warnings'].append("Missing EOF marker")
            
            return True, None, validation_results
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'validate_pdf', 'file': str(pdf_path)})
            validation_results['errors'].append(str(e))
            return False, str(e), validation_results
    
    def repair_pdf(self, pdf_path: Path, output_path: Optional[Path] = None) -> Tuple[bool, Path]:
        """Attempt to repair a corrupted PDF."""
        
        output_path = output_path or pdf_path
        
        try:
            with AtomicFileOperation(output_path, "pdf_repair") as temp_file:
                try:
                    # Open with PyMuPDF (it can handle some corruption)
                    doc = fitz.open(str(pdf_path))
                    
                    # Create new document
                    new_doc = fitz.open()
                    
                    # Copy pages that can be read
                    pages_copied = 0
                    for i in range(len(doc)):
                        try:
                            page = doc[i]
                            new_doc.insert_pdf(doc, from_page=i, to_page=i)
                            pages_copied += 1
                        except Exception as e:
                            self.logger.warning(f"Skipping corrupted page {i+1}: {e}")
                    
                    if pages_copied == 0:
                        raise PDFProcessingError("No pages could be recovered")
                    
                    # Save repaired document
                    new_doc.save(str(temp_file))
                    new_doc.close()
                    doc.close()
                    
                    self.logger.info(f"Repaired PDF: {pages_copied} pages recovered")
                    return True, output_path
                    
                except Exception as e:
                    raise PDFProcessingError(f"Repair failed: {e}")
                    
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'repair_pdf', 'file': str(pdf_path)})
            return False, pdf_path


class PDFProcessor:
    """Main PDF processing class with all operations."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.metadata_handler = PDFMetadata()
        self.validator = PDFValidator()
        self._open_documents: Dict[str, fitz.Document] = {}
    
    def process_pdf_with_date_change(self, pdf_path: Path, new_date: datetime,
                                    update_metadata: bool = True) -> Tuple[bool, Dict[str, Any]]:
        """Process PDF and update its dates."""
        
        result = {
            'success': False,
            'original_metadata': {},
            'new_metadata': {},
            'validation': {},
            'errors': []
        }
        
        try:
            # Validate PDF first
            is_valid, error, validation = self.validator.validate_pdf(pdf_path)
            result['validation'] = validation
            
            if not is_valid:
                if len(validation.get('errors', [])) > 0:
                    # Try to repair
                    self.logger.warning(f"PDF validation failed, attempting repair: {error}")
                    repair_success, repaired_path = self.validator.repair_pdf(pdf_path)
                    
                    if not repair_success:
                        result['errors'].append(f"PDF is invalid and cannot be repaired: {error}")
                        return False, result
                    
                    pdf_path = repaired_path
                else:
                    # Just warnings, continue
                    self.logger.info("PDF has warnings but is processable")
            
            # Read original metadata
            result['original_metadata'] = self.metadata_handler.read_metadata(pdf_path)
            
            # Update metadata if requested
            if update_metadata:
                metadata_updates = {
                    'modDate': new_date,
                    'creationDate': new_date,
                }
                
                self.metadata_handler.update_metadata(pdf_path, metadata_updates)
                
                # Read updated metadata
                result['new_metadata'] = self.metadata_handler.read_metadata(pdf_path)
            
            result['success'] = True
            return True, result
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'process_pdf_with_date_change', 'file': str(pdf_path)})
            result['errors'].append(str(e))
            return False, result
    
    def open_pdf(self, pdf_path: Path) -> Optional[fitz.Document]:
        """Open a PDF document and cache it."""
        
        path_str = str(pdf_path)
        
        if path_str in self._open_documents:
            return self._open_documents[path_str]
        
        try:
            doc = fitz.open(path_str)
            self._open_documents[path_str] = doc
            return doc
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'open_pdf', 'file': path_str})
            return None
    
    def close_pdf(self, pdf_path: Path):
        """Close an open PDF document."""
        
        path_str = str(pdf_path)
        
        if path_str in self._open_documents:
            try:
                self._open_documents[path_str].close()
            except:
                pass
            finally:
                del self._open_documents[path_str]
    
    def get_pdf_preview(self, pdf_path: Path, page_num: int = 0, 
                       zoom: float = 1.0) -> Optional[bytes]:
        """Generate a preview image of a PDF page."""
        
        try:
            doc = self.open_pdf(pdf_path)
            
            if not doc or page_num >= len(doc):
                return None
            
            page = doc[page_num]
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            return pix.tobytes("png")
            
        except Exception as e:
            log_exception(self.logger, e, {
                'operation': 'get_pdf_preview',
                'file': str(pdf_path),
                'page': page_num
            })
            return None
    
    def extract_pdf_info(self, pdf_path: Path) -> Dict[str, Any]:
        """Extract comprehensive information from a PDF."""
        
        info = {
            'file_path': str(pdf_path),
            'file_size': pdf_path.stat().st_size if pdf_path.exists() else 0,
            'page_count': 0,
            'metadata': {},
            'validation': {},
            'text_preview': '',
            'has_images': False,
            'has_forms': False,
        }
        
        try:
            # Get validation info
            is_valid, error, validation = self.validator.validate_pdf(pdf_path)
            info['validation'] = validation
            
            if is_valid:
                # Get metadata
                info['metadata'] = self.metadata_handler.read_metadata(pdf_path)
                
                # Open document for detailed info
                doc = self.open_pdf(pdf_path)
                
                if doc:
                    info['page_count'] = len(doc)
                    
                    # Get text preview from first page
                    if len(doc) > 0:
                        try:
                            text = doc[0].get_text()[:500]
                            info['text_preview'] = text.strip()
                        except:
                            pass
                    
                    # Check for images and forms
                    for page in doc:
                        if page.get_images():
                            info['has_images'] = True
                        if page.widgets():
                            info['has_forms'] = True
                        if info['has_images'] and info['has_forms']:
                            break
            
        except Exception as e:
            log_exception(self.logger, e, {'operation': 'extract_pdf_info', 'file': str(pdf_path)})
            info['error'] = str(e)
        
        return info
    
    def cleanup(self):
        """Close all open documents."""
        
        for path_str in list(self._open_documents.keys()):
            try:
                self._open_documents[path_str].close()
            except:
                pass
        
        self._open_documents.clear()