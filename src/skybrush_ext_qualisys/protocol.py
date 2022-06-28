from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Union


class QualisysRTPacketType(IntEnum):
    """Enum representing the possible Qualisys RT packet types."""

    ERROR = 0
    COMMAND = 1
    XML = 2
    DATA = 3
    NO_MORE_DATA = 4
    C3D_FILE = 5
    EVENT = 6
    DISCOVER = 7
    QTM_FILE = 8


class QualisysRTEvent(IntEnum):
    """Enum representing the possible event types in a Qualisys RT event packet."""

    CONNECTED = 1
    CONNECTION_CLOSED = 2
    CAPTURE_STARTED = 3
    CAPTURE_STOPPED = 4
    CALIBRATION_STARTED = 6
    CALIBRATION_STOPPED = 7
    RT_FROM_FILE_STARTED = 8
    RT_FROM_FILE_STOPPED = 9
    WAITING_FOR_TRIGGER = 10
    CAMERA_SETTINGS_CHANGED = 11
    QTM_SHUTTING_DOWN = 12
    CAPTURE_SAVED = 13
    REPROCESSING_STARTED = 14
    REPROCESSING_STOPPED = 15
    TRIGGER = 16


class QualisysRTError(RuntimeError):
    """Error that is raised when an error packet is received from a Qualisys RT
    connection.
    """

    pass


def _ensure_bytes(value: Union[str, bytes], *, encoding: str = "utf-8") -> bytes:
    return value if isinstance(value, bytes) else value.encode(encoding)


@dataclass
class QualisysRTMessage:
    """Data class representing a single message in the Qualisys RT protocol."""

    type: QualisysRTPacketType
    """The type of the message"""

    body: bytes
    """The body of the message"""

    @classmethod
    def create_command(cls, command: Union[str, bytes], *args: Union[str, bytes]):
        all_args = [_ensure_bytes(command)]
        all_args.extend(_ensure_bytes(x) for x in args)
        return cls(type=QualisysRTPacketType.COMMAND, body=b" ".join(all_args))

    @classmethod
    def from_type_and_body(cls, type: int, body: bytes):
        if type in (1, 2, 3):
            # these packets contain null-terminated strings so we strip the
            # null byte
            return cls(
                type=QualisysRTPacketType(type),
                body=body[:-1] if body[-1] == 0 else body,
            )
        else:
            return cls(type=QualisysRTPacketType(type), body=body)

    @property
    def event_code(self) -> Optional[int]:
        """Returns the event code if this packet is an event packet, ``None``
        otherwise.
        """
        if self.type is QualisysRTPacketType.EVENT and len(self.body) > 0:
            return self.body[0]
        else:
            return None

    @property
    def is_command(self) -> bool:
        """Returns whether this packet is a command or response."""
        return self.type is QualisysRTPacketType.COMMAND

    @property
    def is_error(self) -> bool:
        """Returns whether this packet is an error."""
        return self.type is QualisysRTPacketType.ERROR

    def raise_if_error(self) -> None:
        """Raises a QualisysRTError exception if this packet is an error packet."""
        if self.type is QualisysRTPacketType.ERROR:
            raise QualisysRTError(self.body.decode("utf-8", "replace"))
