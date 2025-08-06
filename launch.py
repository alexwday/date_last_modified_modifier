#!/usr/bin/env python3
"""
Launch script for PDF Date Modifier Application
Ensures proper environment setup and error handling
"""

import sys
import os
import logging
from pathlib import Path


def check_dependencies():
    """Check if all required dependencies are installed."""
    
    missing = []
    
    try:
        import PyQt6
    except ImportError:
        missing.append("PyQt6")
    
    try:
        import smb
    except ImportError:
        missing.append("pysmb")
    
    try:
        import fitz
    except ImportError:
        missing.append("PyMuPDF")
    
    try:
        import cryptography
    except ImportError:
        missing.append("cryptography")
    
    if missing:
        print("Missing dependencies detected!")
        print("Please install the following packages:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nRun: pip install -r requirements_robust.txt")
        return False
    
    return True


def setup_environment():
    """Setup application environment."""
    
    # Add src directory to path
    src_path = Path(__file__).parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    
    # Create necessary directories
    dirs_to_create = [
        Path.home() / ".pdf_date_modifier",
        Path.home() / ".pdf_date_modifier" / "logs",
        Path.home() / ".pdf_date_modifier" / "backups",
    ]
    
    for directory in dirs_to_create:
        directory.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables if needed
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def main():
    """Main entry point."""
    
    print("=" * 50)
    print("PDF Date Modifier - Robust Edition")
    print("=" * 50)
    
    # Check dependencies
    print("Checking dependencies...")
    if not check_dependencies():
        sys.exit(1)
    
    # Setup environment
    print("Setting up environment...")
    setup_environment()
    
    # Launch application
    print("Launching application...")
    print("-" * 50)
    
    try:
        from pdf_date_modifier_app import main as app_main
        app_main()
        
    except KeyboardInterrupt:
        print("\nApplication terminated by user")
        sys.exit(0)
        
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        print("\nPlease check the logs at:")
        print(f"  {Path.home() / '.pdf_date_modifier' / 'logs'}")
        
        # Try to log the error
        try:
            log_file = Path.home() / ".pdf_date_modifier" / "logs" / "crash.log"
            with open(log_file, "a") as f:
                import traceback
                f.write(f"\n{'=' * 50}\n")
                f.write(f"Crash at {datetime.now()}\n")
                f.write(traceback.format_exc())
        except:
            pass
        
        sys.exit(1)


if __name__ == "__main__":
    main()