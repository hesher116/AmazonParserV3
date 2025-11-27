"""Utility script to cleanup port 5000"""
import subprocess
import sys

def cleanup_port(port=5000):
    """Kill all processes using the specified port."""
    try:
        # Get all connections on port
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True
        )
        
        pids = set()
        for line in result.stdout.split('\n'):
            if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line or 'CLOSE_WAIT' in line):
                parts = line.split()
                if len(parts) > 4:
                    pid = parts[-1]
                    try:
                        pids.add(int(pid))
                    except ValueError:
                        pass
        
        if not pids:
            print(f"No processes found using port {port}")
            return
        
        print(f"Found {len(pids)} process(es) using port {port}")
        for pid in pids:
            try:
                print(f"Killing process {pid}...")
                subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                             capture_output=True, check=True)
                print(f"OK: Process {pid} killed")
            except subprocess.CalledProcessError as e:
                print(f"ERROR: Failed to kill process {pid}: {e}")
        
        print(f"Port {port} should now be free")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    cleanup_port(port)

