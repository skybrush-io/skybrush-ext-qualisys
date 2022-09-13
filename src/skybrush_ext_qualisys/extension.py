from contextlib import aclosing, ExitStack
from math import isnan
from trio import sleep
from typing import List, TYPE_CHECKING
from xml.etree.ElementTree import fromstring as parse_xml

from flockwave.connections import create_connection, RWConnection
from flockwave.server.ext.base import Extension
from flockwave.server.model import ConnectionPurpose

from skybrush_ext_qualisys.channel import QTMConnection
from skybrush_ext_qualisys.protocol import QualisysRTError

if TYPE_CHECKING:
    from flockwave.server.app import SkybrushServer
    from flockwave.server.ext.motion_capture import MotionCaptureFrame

__all__ = ("QualisysMocapExtension",)

DEFAULT_CONNECTION_URL = "tcp://localhost:22223"
"""Default connection URL to the Qualisys Track Manager."""


TRACKING_LOST = None, None
"""Special entry that denotes a rigid body for which the tracking has been
lost temporarily.
"""


class QualisysMocapExtension(Extension):
    """Template for Skybrush Server extensions."""

    async def run(self, app: "SkybrushServer", configuration, logger):
        """This function is called when the extension was loaded.

        The signature of this function is flexible; you may use zero, one, two
        or three positional arguments after ``self``. The extension manager
        will detect the number of positional arguments and pass only the ones
        that you expect.

        Parameters:
            app: the Skybrush server application that the extension belongs to.
                Also available as ``self.app``.
            configuration: the configuration object. Also available in the
                ``configure()`` method.
            logger: Python logger object that the extension may use. Also
                available as ``self.log``.
        """
        connection_url = configuration.get("connection", DEFAULT_CONNECTION_URL)
        connection = create_connection(connection_url)

        with ExitStack() as stack:
            stack.enter_context(
                app.connection_registry.use(
                    connection,
                    "qualisys",
                    "Qualisys QTM-RT connection",
                    purpose=ConnectionPurpose.mocap,  # type: ignore
                )
            )

            if self.log:
                self.log.info(f"Using Qualisys Track Manager at {connection_url}")

            await app.supervise(connection, task=self.handle_qtm_connection)  # type: ignore

    async def handle_qtm_connection(
        self, connection: RWConnection[bytes, bytes]
    ) -> None:
        if self.log:
            self.log.info(
                "Connected to Qualisys Track Manager.", extra={"semantics": "success"}
            )

        try:
            await self._handle_qtm_connection(QTMConnection(connection))
        except QualisysRTError as ex:
            if self.log:
                self.log.error(f"QTM returned unexpected error: {ex}")
        except RuntimeError as ex:
            if self.log:
                self.log.error(str(ex))
        except Exception:
            if self.log:
                self.log.exception("Unexpected error while handling connection to QTM")
        finally:
            if self.log:
                self.log.info("Connection to QTM closed.")
            await connection.close()

    async def _handle_qtm_connection(self, conn: QTMConnection) -> None:
        if not await conn.wait_for_banner():
            return

        assert self.log is not None

        # Send version command
        await conn.switch_to_version("1.23")

        # Wait for some rigid bodies to appear
        bodies: List[str] = []
        while not bodies:
            response = await conn.send_command("GetParameters", "6d")
            parsed_response = parse_xml(response.body)
            bodies = [
                body.text.strip()  # type: ignore
                for body in parsed_response.findall("*/Body/Name")
            ]
            if not bodies:
                await sleep(1)

        # TODO(ntamas): we should check periodically whether GetParameters still
        # returns the same number of rigid bodies, and update if the setup
        # changes

        try:
            self.log.info(f"Found {len(bodies)} rigid bodies, streaming frames")
            await self._stream_frames_from_qtm_connection(conn, bodies)
        finally:
            self.log.info("Streaming terminated.")

    async def _stream_frames_from_qtm_connection(
        self, conn: QTMConnection, bodies: List[str]
    ) -> None:
        assert self.app is not None
        assert self.log is not None

        # Grab the signal we need to post frames, as well as the frame factory
        # from the motion_capture extension
        create_frame = self.app.import_api("motion_capture").create_frame
        enqueue_frame = self.app.import_api("motion_capture").enqueue_frame

        async with aclosing(conn.stream_frames("AllFrames", "6D")) as stream:  # type: ignore
            async for packet in stream:
                _, component_6d = packet.get_6d()
                if len(component_6d) != len(bodies):
                    # Rigid body count seems to have changed. This is okay, we
                    # just terminate the connection with a warning, and the
                    # connection supervisor will open it again as soon as
                    # possible
                    self.log.warn(
                        f"Expected {len(bodies)} rigid bodies in frame, "
                        f"got {len(component_6d)}, terminating stream"
                    )
                    return

                frame: MotionCaptureFrame = create_frame()
                for name, (pos, _) in zip(bodies, component_6d):
                    if any(isnan(x) for x in pos):
                        pos = None
                    if pos:
                        # TODO(ntamas): configure units!
                        position, attitude = (
                            pos.x / 1000.0,
                            pos.y / 1000.0,
                            pos.z / 1000.0,
                        ), None
                    else:
                        position, attitude = TRACKING_LOST

                    frame.add_item(name, position, attitude)

                enqueue_frame(frame)
