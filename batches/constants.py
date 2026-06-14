"""
batches/constants.py
Fixed timetable slot definitions (E4).
"""
from datetime import time

# Maps slot_code → (start_time, end_time)
FIXED_SLOTS = {
    'P1': (time(8, 0),   time(10, 0)),
    'P2': (time(10, 15), time(12, 15)),
    'P3': (time(12, 45),  time(14, 45)),
    'P4': (time(15, 00), time(17, 00)),
}

# Duration (in minutes) added to start_time for session types that auto-compute end_time
SESSION_DURATIONS = {
    'class_test': 90,
    'prelim':     180,
    'practice':   90,
}
