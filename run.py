"""Entry point for Amazon Parser application"""
import os
import sys
import signal
import atexit

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import app
from utils.logger import get_logger

logger = get_logger(__name__)


def cleanup_chrome_processes():
    """Kill any remaining Chrome processes."""
    try:
        import subprocess
        import platform
        
        if platform.system() == 'Windows':
            # Kill Chrome processes on Windows (only chromedriver, not user Chrome)
            result = subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                logger.info("Cleaned up chromedriver processes")
        else:
            # Kill Chrome processes on Linux/Mac
            subprocess.run(['pkill', '-f', 'chromedriver'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
            logger.info("Cleaned up chromedriver processes")
    except Exception as e:
        logger.debug(f"Cleanup error (may be normal): {e}")


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("Shutdown signal received, cleaning up...")
    cleanup_chrome_processes()
    sys.exit(0)


def main():
    """Run the Flask application."""
    # Register cleanup handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_chrome_processes)
    
    # Clean up any leftover chromedriver processes on startup (not user Chrome)
    try:
        cleanup_chrome_processes()
    except Exception as e:
        logger.debug(f"Startup cleanup skipped: {e}")
    
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'
    
    # Check if port 5000 is available, if not - cleanup
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.close()
    except OSError:
        logger.warning(f"Port {port} is busy, attempting to cleanup...")
        # Try to cleanup port using PowerShell
        try:
            import subprocess
            import platform
            if platform.system() == 'Windows':
                # Use PowerShell to find and kill processes
                ps_script = f'''
                $connections = Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue
                if ($connections) {{
                    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
                    foreach ($pid in $pids) {{
                        Write-Host "Killing process $pid"
                        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                    }}
                    Start-Sleep -Seconds 2
                }}
                '''
                result = subprocess.run(
                    ['powershell', '-Command', ps_script],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    logger.info("Port cleanup completed")
                else:
                    logger.warning("Port cleanup may have failed, trying alternative method...")
                    # Fallback: use cleanup script
                    try:
                        subprocess.run([sys.executable, 'cleanup_port.py', str(port)], 
                                     timeout=10, capture_output=True)
                    except:
                        pass
                
                # Wait a bit and try again
                import time
                time.sleep(2)
                
                # Check again
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.bind((host, port))
                    sock.close()
                    logger.info("Port is now available")
                except OSError:
                    logger.error(f"Port {port} is still busy after cleanup")
                    logger.info("Please run: python cleanup_port.py")
                    sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to cleanup port: {e}")
            logger.info(f"Please run: python cleanup_port.py {port}")
            sys.exit(1)
    
    # Cleanup old tasks on startup
    cleanup_old_tasks()
    
    # Schedule periodic cleanup (every 24 hours)
    import threading
    def periodic_cleanup():
        import time
        while True:
            time.sleep(24 * 60 * 60)  # 24 hours
            cleanup_old_tasks()
    
    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    
    logger.info("=" * 60)
    logger.info(f"Starting Amazon Parser on http://{host}:{port}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Headless mode: {os.getenv('AMAZON_PARSER_HEADLESS', 'false')}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    logger.info(f"Open in browser: http://{host}:{port}")
    
    # Store server reference for cleanup
    server = None
    
    try:
        # Use threaded mode for better cleanup
        from werkzeug.serving import make_server
        server = make_server(host, port, app, threaded=True)
        logger.info(f"Server started on http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        if server:
            try:
                server.shutdown()
            except:
                pass
        cleanup_chrome_processes()
    except Exception as e:
        logger.error(f"Failed to start Flask: {e}")
        import traceback
        logger.error(traceback.format_exc())
        if server:
            try:
                server.shutdown()
            except:
                pass
        cleanup_chrome_processes()


def cleanup_old_tasks():
    """Periodically cleanup old tasks from database."""
    from core.database import Database
    db = Database()
    try:
        deleted = db.cleanup_old_tasks()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old tasks")
    except Exception as e:
        logger.error(f"Failed to cleanup old tasks: {e}")


if __name__ == '__main__':
    main()

