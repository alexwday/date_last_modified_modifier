# PDF Date Modifier - Robust Edition

A professional, enterprise-grade application for modifying PDF file dates on network-attached storage (NAS) systems. This completely rebuilt version focuses on robustness, comprehensive logging, and error recovery.

## Key Features

### Core Functionality
- **PDF Date Modification**: Modify creation and modification dates of PDF files
- **NAS Support**: Direct integration with SMB/CIFS network shares
- **Batch Processing**: Process multiple files at once
- **PDF Validation**: Automatic validation and repair of corrupted PDFs
- **Metadata Updates**: Update internal PDF metadata alongside file system dates

### Robustness Features
- **Comprehensive Logging**: Multi-level logging with rotation and structured output
- **Connection Pooling**: Efficient connection management with automatic retry
- **Atomic Operations**: All file operations are atomic with automatic rollback on failure
- **Error Recovery**: Automatic error detection and recovery mechanisms
- **Health Monitoring**: Real-time connection and thread health monitoring
- **Graceful Degradation**: Continue operation even when some components fail

### Architecture Improvements
- **Modular Design**: Clean separation of concerns with dedicated modules
- **Thread Management**: Proper thread lifecycle management with monitoring
- **Configuration Management**: Centralized configuration with validation
- **Security**: Encrypted password storage and secure connections
- **Performance**: Connection pooling and optimized file operations

## Installation

### Prerequisites
- Python 3.8 or higher
- macOS, Linux, or Windows

### Setup

1. Clone or download the repository:
```bash
cd /Users/alexwday/Projects/date_modified_modifier
```

2. Install dependencies:
```bash
pip install -r requirements_robust.txt
```

3. Launch the application:
```bash
python launch.py
```

Or make the launch script executable:
```bash
chmod +x launch.py
./launch.py
```

## Project Structure

```
date_modified_modifier/
│
├── src/
│   ├── core/                      # Core functionality modules
│   │   ├── __init__.py
│   │   ├── logging_config.py      # Comprehensive logging system
│   │   ├── config_manager.py      # Configuration management
│   │   ├── connection_manager.py  # SMB connection handling
│   │   ├── file_operations.py     # Atomic file operations
│   │   ├── pdf_processor.py       # PDF processing and validation
│   │   └── thread_manager.py      # Thread lifecycle management
│   │
│   └── ui/                        # User interface components
│       ├── __init__.py
│       └── main_window.py         # Main window and dialogs
│
├── pdf_date_modifier_app.py       # Main application
├── launch.py                      # Launch script with checks
├── requirements_robust.txt        # Dependencies
└── README_ROBUST.md              # This file
```

## Configuration

Configuration is stored in `~/.pdf_date_modifier/config.json` with the following structure:

```json
{
  "server": {
    "nas_ip": "192.168.1.100",
    "username": "your_username",
    "password": "encrypted_password",
    "share_name": "documents",
    "base_path": "/Archive/Scanned",
    "port": 445,
    "timeout": 30
  },
  "app": {
    "log_level": "INFO",
    "max_worker_threads": 5,
    "connection_pool_size": 3,
    "auto_advance": true,
    "update_pdf_metadata": true,
    "repair_corrupted_pdfs": true
  }
}
```

### Environment Variables

You can override configuration using environment variables:
- `PDF_MOD_NAS_IP`: NAS IP address
- `PDF_MOD_USERNAME`: SMB username
- `PDF_MOD_PASSWORD`: SMB password
- `PDF_MOD_SHARE`: Share name
- `PDF_MOD_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Logging

The application provides comprehensive logging at multiple levels:

### Log Files
- **Application Log**: `~/.pdf_date_modifier/logs/pdf_date_modifier.log`
  - Contains all application events and debug information
  - Rotates at 10MB with 5 backups

- **Error Log**: `~/.pdf_date_modifier/logs/pdf_date_modifier_errors.log`
  - Contains only errors and critical issues
  - Rotates at 5MB with 3 backups

- **Structured Log**: `~/.pdf_date_modifier/logs/pdf_date_modifier_structured.jsonl`
  - JSON-formatted logs for analysis
  - Rotates at 20MB with 3 backups

### Log Viewer
Access the built-in log viewer from the menu: `View > View Logs`

## Features in Detail

### Connection Management
- **Connection Pooling**: Maintains multiple connections for better performance
- **Automatic Retry**: Configurable retry logic with exponential backoff
- **Health Monitoring**: Tracks connection health and automatically recovers
- **Keepalive**: Maintains connections with periodic health checks

### File Operations
- **Atomic Operations**: All file modifications are atomic
- **Automatic Backup**: Creates backups before modifications
- **Rollback Support**: Automatic rollback on failure
- **Checksum Verification**: Validates file integrity
- **Platform Support**: Works on macOS, Linux, and Windows

### PDF Processing
- **Validation**: Comprehensive PDF validation
- **Repair**: Automatic repair of corrupted PDFs
- **Metadata Handling**: Read and update PDF metadata
- **Preview Generation**: Generate PDF previews at any zoom level
- **Multi-page Support**: Handle multi-page PDFs

### Thread Management
- **Thread Pool**: Configurable worker thread pool
- **Task Priority**: Priority-based task execution
- **Monitoring**: Real-time thread monitoring
- **Graceful Shutdown**: Proper cleanup on exit
- **Error Recovery**: Automatic retry on task failure

## Usage Guide

### Basic Workflow

1. **Connect to NAS**
   - Click "Connect" or press `Ctrl+K`
   - Enter your NAS credentials
   - Test connection before saving

2. **Browse Files**
   - Files are automatically loaded after connection
   - Use search box to filter files
   - Click on a file to preview it

3. **Modify Date**
   - Select a file from the list
   - Choose new date using the date picker
   - Click "Apply" or press `Ctrl+M`
   - File automatically advances to next (if enabled)

### Batch Processing

1. Select `Tools > Batch Process`
2. Set the desired date
3. Confirm to apply to all files
4. Monitor progress in status bar

### Keyboard Shortcuts

- `Ctrl+K`: Connect to NAS
- `Ctrl+L`: View logs
- `Ctrl+M`: Apply date modification
- `F5`: Refresh file list
- `Right/Left`: Navigate pages
- `Ctrl+Right/Left`: Navigate files
- `Ctrl++/-`: Zoom in/out
- `Ctrl+0`: Reset zoom

## Troubleshooting

### Connection Issues

1. **Check Credentials**: Verify username and password
2. **Network Access**: Ensure NAS is accessible from your network
3. **Firewall**: Check that port 445 (SMB) is not blocked
4. **Logs**: Check application logs for detailed error messages

### PDF Processing Issues

1. **Validation**: Use `Tools > Validate All PDFs` to check files
2. **Repair**: Application automatically attempts to repair corrupted PDFs
3. **Metadata**: Check if PDF metadata update is enabled in settings

### Performance Issues

1. **Thread Count**: Adjust `max_worker_threads` in configuration
2. **Connection Pool**: Increase `connection_pool_size` for better throughput
3. **Logging Level**: Set to `WARNING` or `ERROR` for production use

## Error Recovery

The application includes multiple layers of error recovery:

1. **Connection Recovery**: Automatic reconnection on network issues
2. **File Recovery**: Automatic rollback on file operation failures
3. **PDF Recovery**: Automatic repair of corrupted PDFs
4. **Thread Recovery**: Automatic restart of failed worker threads

## Monitoring

### Statistics View
Access `View > Statistics` to see:
- Active threads and tasks
- Success/failure rates
- Connection health
- Performance metrics

### Health Checks
The application performs continuous health checks:
- Connection keepalive every 60 seconds
- Thread monitoring every second
- Automatic cleanup of stale resources

## Security

- **Encrypted Storage**: Passwords are encrypted using Fernet encryption
- **Secure Connections**: Uses NTLMv2 authentication by default
- **No Plaintext**: Passwords never stored in plaintext
- **File Permissions**: Restrictive permissions on configuration files

## Development

### Running Tests
```bash
pytest tests/ -v --cov=src
```

### Code Quality
```bash
# Format code
black src/ tests/

# Lint code
pylint src/

# Type checking
mypy src/
```

## Support

### Logs Location
- macOS/Linux: `~/.pdf_date_modifier/logs/`
- Windows: `%USERPROFILE%\.pdf_date_modifier\logs\`

### Configuration Location
- macOS/Linux: `~/.pdf_date_modifier/config.json`
- Windows: `%USERPROFILE%\.pdf_date_modifier\config.json`

### Common Issues

**Q: Application crashes on startup**
A: Check that all dependencies are installed: `pip install -r requirements_robust.txt`

**Q: Cannot connect to NAS**
A: Verify credentials and ensure SMB/CIFS is enabled on your NAS

**Q: PDFs not updating**
A: Check logs for errors and ensure you have write permissions on the NAS

**Q: Slow performance**
A: Increase thread count and connection pool size in configuration

## License

This software is provided as-is for personal and educational use.

## Version History

### Version 2.0.0 - Robust Edition
- Complete rewrite with focus on robustness
- Comprehensive logging system
- Connection pooling and retry logic
- Atomic file operations
- PDF validation and repair
- Thread management
- Health monitoring
- Error recovery mechanisms

### Version 1.0.0 - Original
- Basic PDF date modification
- Simple NAS connection
- Basic UI

## Notes

This robust version addresses all the stability issues from the original version:
- No more random crashes
- Comprehensive logging for debugging
- Automatic error recovery
- Better resource management
- Professional-grade error handling

The application now provides enterprise-level reliability while maintaining ease of use.