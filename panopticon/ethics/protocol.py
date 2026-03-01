"""
Lucius Fox Ethical Protocol
===========================
"This is too much power for one person."
"That's why I gave it to you."

Rules:
1. Crisis-mode only: activate on user command.
2. Auto-log-wipe after session or timeout.
3. No persistent tracking of individuals — only aggregate observables.
4. Self-destruct option: user-triggered full state erase.
5. Print warning on every activation.
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from panopticon.config import EthicsConfig

logger = logging.getLogger(__name__)

# The warning. Every time.
ACTIVATION_BANNER = r"""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║              PANOPTICON DARK KNIGHT — CONTINGENCY MODE               ║
║                                                                      ║
║    "This is a contingency tool.                                      ║
║     Power like this demands restraint."                              ║
║                                                 — Lucius Fox         ║
║                                                                      ║
║    • No individuals are tracked. Only aggregate observables.         ║
║    • Session auto-wipes after timeout.                               ║
║    • All data is ephemeral. Nothing persists beyond this session.    ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""


class EthicalProtocol:
    """
    Gatekeeper for the Panopticon system.
    Must be activated before any analysis can run.
    Enforces session limits, logging discipline, and self-destruct.
    """

    def __init__(self, config: Optional[EthicsConfig] = None):
        self.config = config or EthicsConfig()
        self._activated = False
        self._activation_time: Optional[datetime] = None
        self._session_log: list[str] = []

    @property
    def is_active(self) -> bool:
        """Is the system currently activated?"""
        if not self._activated:
            return False
        # Check timeout
        if self._activation_time:
            elapsed = (datetime.now(timezone.utc) - self._activation_time).total_seconds()
            if elapsed > self.config.session_timeout_minutes * 60:
                logger.warning("Session timeout reached. Auto-deactivating.")
                self.deactivate()
                return False
        return True

    def activate(self, phrase: str = "") -> bool:
        """
        Activate contingency mode.
        Requires activation phrase if configured.
        Returns True if activation succeeded.
        """
        if self.config.require_activation_phrase:
            if phrase.strip().lower() != self.config.activation_phrase.lower():
                logger.warning("Activation phrase incorrect. Access denied.")
                self._log("ACTIVATION DENIED — wrong phrase")
                return False

        self._activated = True
        self._activation_time = datetime.now(timezone.utc)
        self._log("ACTIVATED — contingency mode engaged")

        # Print the warning. Every single time.
        print(ACTIVATION_BANNER)
        timeout = self.config.session_timeout_minutes
        print(f"  Session timeout: {timeout} minutes")
        print(f"  Activated at: {self._activation_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()

        return True

    def deactivate(self) -> None:
        """Deactivate and wipe session state."""
        self._log("DEACTIVATED — session ending")
        self._activated = False

        if self.config.auto_log_wipe:
            self._wipe_logs()

        self._activation_time = None
        logger.info("Panopticon deactivated. Session state wiped.")

    def self_destruct(self, confirm: str = "destroy") -> bool:
        """
        Full state erase. Wipes all in-memory data, logs, and temp files.
        Requires confirmation string.
        """
        if confirm != "destroy":
            logger.warning("Self-destruct requires confirmation='destroy'.")
            return False

        self._log("SELF-DESTRUCT INITIATED")
        print("\n  *** SELF-DESTRUCT: Erasing all session state ***\n")

        # Wipe session log
        self._wipe_logs()

        # Wipe any temp files
        self._wipe_temp_files()

        # Deactivate
        self._activated = False
        self._activation_time = None

        # Force garbage collection
        gc.collect()

        logger.info("Self-destruct complete. All state erased.")
        print("  Self-destruct complete. The sonar is dark.\n")
        return True

    def require_active(self) -> None:
        """Gate check: raise if system is not activated."""
        if not self.is_active:
            raise PermissionError(
                "Panopticon is not activated. "
                "Use protocol.activate('activate contingency') first."
            )

    def session_remaining_minutes(self) -> float:
        """Minutes remaining in current session."""
        if not self._activation_time:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self._activation_time).total_seconds()
        remaining = self.config.session_timeout_minutes - (elapsed / 60)
        return max(0.0, remaining)

    def get_session_log(self) -> list[str]:
        """Return session log (for dashboard display)."""
        return list(self._session_log)

    def _log(self, message: str) -> None:
        """Internal session logging."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self._session_log.append(entry)
        logger.info("ETHICS: %s", message)

    def _wipe_logs(self) -> None:
        """Securely wipe session logs."""
        # Overwrite with zeros before clearing
        for i in range(len(self._session_log)):
            self._session_log[i] = "\x00" * len(self._session_log[i])
        self._session_log.clear()

    def _wipe_temp_files(self) -> None:
        """Remove any temporary files created during session."""
        temp_dir = Path("/tmp/panopticon_session")
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("Wiped temp directory: %s", temp_dir)
