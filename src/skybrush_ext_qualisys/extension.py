from contextlib import aclosing, ExitStack
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

__all__ = ("QualisysMocapExtension",)

DEFAULT_CONNECTION_URL = "tcp://localhost:22223"
"""Default connection URL to the Qualisys Track Manager."""


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
                    purpose=ConnectionPurpose.other,  # type: ignore
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

        self.log.info(f"Found {len(bodies)} rigid bodies")

        async with aclosing(conn.stream_frames("AllFrames", "6D")) as stream:  # type: ignore
            async for packet in stream:
                _, component_6d = packet.get_6d()
                for index, (pos, _) in enumerate(component_6d):
                    name = bodies[index]
                    self.log.info(f"{name}: {pos.x:.2f}, {pos.y:.2f}, {pos.z:.2f}")
