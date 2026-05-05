import threading

_scan_state = {}
_scan_lock  = threading.Lock()
