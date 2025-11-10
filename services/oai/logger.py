"""
Safe logging module that handles file operations in a separate thread
and gracefully handles errors without interrupting the main server.
"""

import asyncio
import threading
from pathlib import Path
from datetime import datetime
from queue import Queue
from typing import Optional
import traceback


class SafeLogger:
    """Thread-safe logger that writes to disk asynchronously."""

    def __init__(self, base_folder: str = "data"):
        self.base_folder = Path(base_folder)
        self.raw_dumps_folder = self.base_folder / "raw_dumps"
        self.queue = Queue()
        self.worker_thread = None
        self.running = False
        self._ensure_folders()
        self._start_worker()

    def _ensure_folders(self):
        """Ensure base folders exist, create if missing."""
        try:
            self.base_folder.mkdir(parents=True, exist_ok=True)
            self.raw_dumps_folder.mkdir(parents=True, exist_ok=True)
            print(f"[SafeLogger] Initialized folders: {self.base_folder}")
        except Exception as e:
            print(f"[SafeLogger] WARNING: Failed to create folders: {e}")
            # Don't raise - we'll try to recreate on each write

    def _start_worker(self):
        """Start the background worker thread."""
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print(f"[SafeLogger] Worker thread started")

    def _worker(self):
        """Background worker that processes the logging queue."""
        while self.running:
            try:
                task = self.queue.get(timeout=1.0)
                if task is None:  # Shutdown signal
                    break

                task_type, args = task

                if task_type == "raw_dump":
                    self._write_raw_dump(*args)
                elif task_type == "conversation_log":
                    self._write_conversation_log(*args)

                self.queue.task_done()

            except Exception as e:
                if "Empty" not in str(type(e).__name__):
                    print(f"[SafeLogger] Worker error: {e}")
                    traceback.print_exc()

    def _write_raw_dump(self, system_message: str, user_prompt: str):
        """Write raw prompt dumps to disk."""
        try:
            # Ensure folder exists
            self.raw_dumps_folder.mkdir(parents=True, exist_ok=True)

            timestamp = int(datetime.now().timestamp())
            system_file = self.raw_dumps_folder / f"system_{timestamp}.md"
            user_file = self.raw_dumps_folder / f"user_{timestamp}.md"

            system_file.write_text(system_message, encoding="utf-8")
            user_file.write_text(user_prompt, encoding="utf-8")

            print(f"[SafeLogger] Raw dump saved: {timestamp}")

        except Exception as e:
            print(f"[SafeLogger] ERROR writing raw dump: {e}")
            # Don't raise - just log the error

    def _write_conversation_log(
        self,
        conversation_id: str,
        index: int,
        system_message: str,
        prompt: str,
        response: str,
    ):
        """Write conversation log to disk."""
        try:
            # Ensure conversation folder exists
            conv_folder = self.base_folder / conversation_id
            conv_folder.mkdir(parents=True, exist_ok=True)

            # Write all three files
            (conv_folder / f"{index}_system.md").write_text(
                system_message, encoding="utf-8"
            )
            (conv_folder / f"{index}_prompt.md").write_text(prompt, encoding="utf-8")
            (conv_folder / f"{index}_response.md").write_text(
                response, encoding="utf-8"
            )

            print(f"[SafeLogger] Conversation log saved: {conversation_id}/{index}")

        except Exception as e:
            print(f"[SafeLogger] ERROR writing conversation log: {e}")
            # Don't raise - just log the error

    def dump_raw_prompts(self, system_message: str, user_prompt: str):
        """
        Queue a raw prompt dump (non-blocking).
        Returns immediately without waiting for write to complete.
        """
        try:
            self.queue.put(("raw_dump", (system_message, user_prompt)))
        except Exception as e:
            print(f"[SafeLogger] ERROR queuing raw dump: {e}")
            # Don't raise - logging failure should not break the server

    def log_conversation(
        self,
        conversation_id: str,
        index: int,
        system_message: str,
        prompt: str,
        response: str,
    ):
        """
        Queue a conversation log (non-blocking).
        Returns immediately without waiting for write to complete.
        """
        try:
            self.queue.put(
                (
                    "conversation_log",
                    (conversation_id, index, system_message, prompt, response),
                )
            )
        except Exception as e:
            print(f"[SafeLogger] ERROR queuing conversation log: {e}")
            # Don't raise - logging failure should not break the server

    def shutdown(self):
        """Gracefully shutdown the worker thread."""
        print(f"[SafeLogger] Shutting down...")
        self.running = False
        self.queue.put(None)  # Shutdown signal
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
        print(f"[SafeLogger] Shutdown complete")


# Global instance
_logger_instance: Optional[SafeLogger] = None


def get_logger() -> SafeLogger:
    """Get or create the global logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = SafeLogger()
    return _logger_instance


def dump_raw_prompts(system_message: str, user_prompt: str):
    """
    Legacy function for compatibility.
    Logs raw prompts asynchronously without blocking.
    """
    try:
        logger = get_logger()
        logger.dump_raw_prompts(system_message, user_prompt)
    except Exception as e:
        print(f"[SafeLogger] CRITICAL: Failed to log raw prompts: {e}")
        # Never raise - logging should not break the server
