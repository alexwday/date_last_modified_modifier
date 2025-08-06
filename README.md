# NAS PDF Date Modifier

A Python application that connects to a NAS drive via SMB/CIFS, allows you to browse PDF files, preview them, and modify their "last modified" dates based on the actual document dates you find within the PDFs.

## Features

- Connect to NAS drives using NTLM authentication over SMB
- Browse and list PDF files from a specified path
- Preview PDFs with page navigation
- Modify file modification dates on the NAS
- Process multiple files sequentially

## Prerequisites

- Python 3.8 or higher
- Access to a NAS drive with SMB/CIFS support
- NAS credentials (IP address, username, password, share name)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/alexwday/date_last_modified_modifier.git
cd date_last_modified_modifier
```

### 2. Create a Virtual Environment

```bash
# On macOS/Linux
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### 1. Run the Application

```bash
python nas_pdf_date_modifier.py
```

### 2. Connect to Your NAS

1. Enter your NAS connection details:
   - **NAS IP**: IP address of your NAS (e.g., 192.168.1.100)
   - **Username**: Your NAS username
   - **Password**: Your NAS password
   - **Share**: The share name on your NAS
   - **Path**: The folder path within the share (leave empty for root)

2. Click **Connect** to establish connection and list PDF files

### 3. Process PDF Files

1. **Select a File**: Click on a PDF file from the list to load it
2. **Navigate Pages**: Use the Previous/Next buttons to browse through the PDF pages
3. **Find Document Date**: Look for the actual document date within the PDF
4. **Enter New Date**: Type the document date in the format `YYYY-MM-DD HH:MM:SS`
5. **Modify Date**: Click "Modify Date" to update the file's modification time on the NAS
6. **Next File**: Click "Next File" to move to the next PDF in the list

## Date Format

The application expects dates in the following format:
- `YYYY-MM-DD HH:MM:SS` (e.g., 2024-03-15 14:30:00)

## Requirements

The application requires the following Python packages:
- `pysmb` - For SMB/CIFS connection to NAS
- `PyMuPDF` - For PDF rendering and display
- `Pillow` - For image processing

## Troubleshooting

### Connection Issues
- Ensure your NAS IP is accessible from your computer
- Verify your username and password are correct
- Check that the share name exists and you have access to it
- Make sure SMB/CIFS is enabled on your NAS

### PDF Display Issues
- Some PDFs may not display correctly if they use unusual encoding
- Try updating PyMuPDF if you encounter rendering issues

### Date Modification Errors
- Ensure you have write permissions on the NAS share
- Some NAS systems may not support direct time modification; the app will try alternative methods automatically

## Security Note

Your NAS credentials are only used for the current session and are not stored permanently. Always ensure you're on a secure network when connecting to your NAS.

## License

MIT License

## Author

Alex W Day