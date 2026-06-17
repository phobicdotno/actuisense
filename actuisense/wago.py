"""
Listen on a WAGO PLC's CAN interface (can0) over SSH.

A WAGO PFC200 sits on the same NMEA 2000 backbone as the gateway and exposes the
bus as a SocketCAN interface (``can0``). Logging in with a username/password and
running ``candump`` streams every raw CAN frame on the wire — which is the ground
truth for what the gateway is actually transmitting/receiving, independent of the
gateway's own report.

This module SSHes in (paramiko), runs ``candump -L <iface>``, and yields decoded
:class:`~actuisense.can.CanFrame` objects. paramiko is imported lazily so the core
package keeps depending only on pyserial + textual; install the extra with
``pip install actuisense[wago]`` (or just ``pip install paramiko``).

The candump line source is injectable, so the parsing/stop logic is unit-testable
without any SSH connection or hardware.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable, Iterator, Optional

from .can import CanFrame, parse_candump_line

DEFAULT_IFACE = "can0"
DEFAULT_SSH_PORT = 22
# -L = log format "(ts) iface id#data", the easiest to parse and the can-utils
# standard for piping/replay.
CANDUMP_TEMPLATE = "candump -L {iface}"


class WagoError(Exception):
    pass


class CandumpSource:
    """Yields :class:`CanFrame`s from a line-oriented ``candump`` stream.

    ``lines`` is any iterable of text lines (one candump record each); ``closer``
    is called by :meth:`close` to tear down the underlying connection. Use
    :meth:`over_ssh` to build one backed by a live SSH session.
    """

    def __init__(
        self,
        lines: Iterable[str],
        closer: Optional[Callable[[], None]] = None,
        name: str = "can0",
    ) -> None:
        self._lines = lines
        self._closer = closer
        self._name = name
        self._stop = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    def frames(self) -> Iterator[CanFrame]:
        """Iterate decoded N2K frames until the stream ends or :meth:`close` is
        called. Non-N2K / unparseable lines are silently skipped."""
        for line in self._lines:
            if self._stop.is_set():
                return
            frame = parse_candump_line(line)
            if frame is not None:
                yield frame

    def close(self) -> None:
        self._stop.set()
        if self._closer is not None:
            try:
                self._closer()
            except Exception:
                pass
            self._closer = None

    @classmethod
    def over_ssh(
        cls,
        host: str,
        username: str,
        password: str,
        iface: str = DEFAULT_IFACE,
        port: int = DEFAULT_SSH_PORT,
        command: Optional[str] = None,
        connect_timeout: float = 10.0,
    ) -> "CandumpSource":
        """Open an SSH session to ``host`` and start ``candump`` on ``iface``.

        Authenticates with ``username``/``password`` only (no key/agent probing,
        so it works against appliance accounts like WAGO's ``root``/``wago``).
        Raises :class:`WagoError` if paramiko is missing or the connection fails.
        """
        try:
            import paramiko  # noqa: PLC0415 — lazy: keep paramiko an optional extra
        except ImportError as e:  # pragma: no cover — exercised only without paramiko
            raise WagoError(
                "paramiko is required for the WAGO/can0 connection. "
                "Install it with: pip install actuisense[wago]"
            ) from e

        cmd = command or CANDUMP_TEMPLATE.format(iface=iface)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=connect_timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            transport = client.get_transport()
            if transport is None:  # pragma: no cover — defensive
                raise WagoError("SSH transport unavailable after connect")
            channel = transport.open_session()
            channel.exec_command(cmd)
            stdout = channel.makefile("r")
        except WagoError:
            client.close()
            raise
        except Exception as e:
            client.close()
            raise WagoError("could not start '%s' on %s: %s" % (cmd, host, e)) from e

        def _close() -> None:
            try:
                channel.close()
            finally:
                client.close()

        return cls(lines=stdout, closer=_close, name="%s@%s:%s" % (username, host, iface))


__all__ = ["CandumpSource", "WagoError", "DEFAULT_IFACE", "DEFAULT_SSH_PORT"]
