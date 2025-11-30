"""Utility script to check if a port is available"""
import sys
import socket

def check_port(port, host='127.0.0.1'):
    """Check if port is available."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.close()
        return True
    except OSError:
        return False

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    if check_port(port):
        print(f"Port {port} is AVAILABLE")
        sys.exit(0)
    else:
        print(f"Port {port} is BUSY")
        sys.exit(1)



