"""Feedback button: current time. Its stdout becomes the button's live text,
polled every FEEDBACK_INTERVAL seconds and refreshed when the menu opens."""
import time

print(time.strftime("%H:%M:%S"))
