"""
batches/constants.py
Fixed timetable slot definitions (E4).
"""
from datetime import time

# Maps slot_code → (start_time, end_time)
FIXED_SLOTS = {
    'P1': (time(9, 0),   time(10, 30)),
    'P2': (time(10, 45), time(12, 15)),
    'P3': (time(13, 0),  time(14, 30)),
    'P4': (time(14, 45), time(16, 15)),
}

# Duration (in minutes) added to start_time for session types that auto-compute end_time
SESSION_DURATIONS = {
    'class_test': 90,
    'prelim':     180,
    'practice':   90,
}
