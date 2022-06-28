from flockwave.channels.message import MessageChannel
from flockwave.connections import Connection
from qtm.packet import QRTPacket
from struct import Struct
from trio import fail_after, move_on_after, Lock
from typing import AsyncIterator, Iterable, List, Optional, Union

from .protocol import QualisysRTEvent, QualisysRTMessage, QualisysRTPacketType

__all__ = ("QTMConnection",)


class QualisysRTMessageParser:
    """Parser object that can be fed with bytes and that yield parsed Qualisys
    RT protocol messages.
    """

    _header_parts: List[bytes]
    """The header bytes currently being parsed."""

    _message_parts: List[bytes]
    """The current message being read."""

    _reading_body: bool = False
    """Whether we are reading the body of a message or its header."""

    _bytes_left: int = 0
    """Remaining length of the header or body part that should be read."""

    def __init__(self):
        self._header_parts = []
        self._message_parts = []
        self._reset()

    def __call__(self, data: bytes) -> Iterable[QualisysRTMessage]:
        start, end = 0, len(data)
        while start < end:
            if end - start > self._bytes_left:
                chunk = data[start : start + self._bytes_left]
                start += self._bytes_left
            else:
                chunk = data[start:] if start > 0 else data
                start = end

            if self._reading_body:
                self._message_parts.append(chunk)
            else:
                self._header_parts.append(chunk)

            self._bytes_left -= len(chunk)
            if not self._bytes_left:
                header = b"".join(self._header_parts)
                if self._reading_body:
                    yield QualisysRTMessage.from_type_and_body(
                        type=int.from_bytes(header[4:], "little"),
                        body=b"".join(self._message_parts),
                    )
                    self._reset()
                else:
                    self._bytes_left = int.from_bytes(header[:4], "little")
                    if self._bytes_left > 8:
                        self._bytes_left -= 8  # header was already read
                        self._reading_body = True
                    elif self._bytes_left == 8:
                        self._reset()
                    else:
                        raise RuntimeError(
                            f"Invalid message length received: {self._bytes_left}"
                        )

    def _reset(self) -> None:
        """Resets the parser state."""
        self._header_parts.clear()
        self._message_parts.clear()
        self._reading_body = False
        self._bytes_left = 8


class QualisysRTMessageEncoder:
    _struct = Struct("<II")

    def __init__(self):
        pass

    def __call__(self, message: QualisysRTMessage) -> bytes:
        length = len(message.body) + 8
        return b"".join(
            (
                length.to_bytes(4, "little"),
                message.type.to_bytes(4, "little"),
                message.body,
            )
        )


class QTMConnection:
    """Connection to a Qualisys Track Manager instance."""

    _channel: MessageChannel[QualisysRTMessage]

    _lock: Lock
    """A lock to ensure that we are not executing multiple commands at the
    same time.
    """

    _timeout: float
    """Default timeout to use when waiting for the response to a command."""

    def __init__(self, connection: Connection, *, timeout: float = 1):
        """Constructor."""
        parser = QualisysRTMessageParser()
        encoder = QualisysRTMessageEncoder()
        self._channel = MessageChannel(connection, parser, encoder)
        self._lock = Lock()
        self._timeout = float(timeout)

    async def send_command(
        self,
        command: Union[str, bytes],
        *args: Union[str, bytes],
        timeout: Optional[float] = None,
    ) -> QualisysRTMessage:
        """Sends a command to the Qualisys Track Manager instance and returns
        the response packet received for the command.
        """
        async with self._lock:  # type: ignore
            await self._channel.send(QualisysRTMessage.create_command(command, *args))
            with fail_after(timeout if timeout is not None else self._timeout):
                while True:
                    response = await self._channel.receive()

                    # Ignore events while waiting for a response, they can
                    # arrive any time
                    if response.type != QualisysRTPacketType.EVENT:
                        break

        response.raise_if_error()
        return response

    async def stream_frames(self, *args: str) -> AsyncIterator[QRTPacket]:
        response = await self.send_command("StreamFrames", *args)
        stream_ended = False
        try:
            async with self._lock:  # type: ignore
                while True:
                    if response.type is QualisysRTPacketType.DATA:
                        yield QRTPacket(response.body)
                    elif response.event_code == QualisysRTEvent.RT_FROM_FILE_STOPPED:
                        # Streaming ended
                        stream_ended = True
                        return
                    else:
                        print(f"Got unexpected message: {response!r}")
                    response = await self._channel.receive()
        finally:
            if not stream_ended:
                await self.send_command("StreamFrames", "Stop")

    async def switch_to_version(self, version: str) -> None:
        """Switches the connection to the given protocol version."""
        message = await self.send_command("Version", version)
        if (
            not message.is_command
            or message.body != f"Version set to {version}".encode("utf-8")
        ):
            raise RuntimeError(f"Failed to set protocol version to {version}")

    async def wait_for_banner(self, timeout: float = 1) -> bool:
        """Waits for the server to emit the welcome message at the start of the
        connection.

        Parameters:
            timeout: maximum number of seconds to wait for the welcome message

        Returns:
            bool: whether the banner was received successfully
        """
        with move_on_after(timeout):
            message = await self._channel.receive()
            if not message.is_command or message.body != b"QTM RT Interface connected":
                return False
            return True
        return False
