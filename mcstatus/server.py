from __future__ import annotations

from abc import ABC
from typing import Optional, TYPE_CHECKING, Tuple
from urllib.parse import urlparse

import dns.resolver
from dns.exception import DNSException
from dns.rdatatype import RdataType

from mcstatus.bedrock_status import BedrockServerStatus, BedrockStatusResponse
from mcstatus.pinger import AsyncServerPinger, PingResponse, ServerPinger
from mcstatus.protocol.connection import (
    TCPAsyncSocketConnection,
    TCPSocketConnection,
    UDPAsyncSocketConnection,
    UDPSocketConnection,
)
from mcstatus.querier import AsyncServerQuerier, QueryResponse, ServerQuerier
from mcstatus.utils import deprecated, retry

if TYPE_CHECKING:
    from typing_extensions import Self


__all__ = ["JavaServer", "BedrockServer", "MinecraftServer", "MinecraftBedrockServer"]


class MCServer(ABC):
    """Base abstract class for a general minecraft server.

    This class only contains the basic logic shared across both java and bedrock versions,
    it doesn't include any version specific settings and it can't be used to make any requests.

    :param str host: The host/ip of the minecraft server.
    :param int port: The port that the server is on.
    :param float timeout: Timeout, in seconds, before failing to connect.
    """

    def __init__(self, host: str, port: int, *, timeout: float = 3):
        self.ensure_valid(host, port)
        self.host = host
        self.port = port
        self.timeout = timeout

    @classmethod
    def lookup(cls, address: str, *, timeout: float = 3) -> Self:
        """Parse the given address into host and port used to make an instance.

        :param str address: This mimics the address field of a server in minecraft
        :param float timeout: Timeout, in seconds, before failing to connect.
        """
        host, port = cls.parse_address(address)
        if port is None:
            raise ValueError("Given address didn't contain port and there's no default port to fallback to.")
        return cls(host, port, timeout=timeout)

    @staticmethod
    def parse_address(address: str) -> Tuple[str, Optional[int]]:
        tmp = urlparse("//" + address)
        if not tmp.hostname:
            raise ValueError(f"Invalid address '{address}'")
        return (tmp.hostname, tmp.port)

    @staticmethod
    def ensure_valid(host: object, port: object) -> None:
        if not isinstance(host, str):
            raise TypeError(f"Host must be a string address, got {type(host)} ({host!r})")
        if not isinstance(port, int):
            raise TypeError(f"Port must be an integer port number, got {type(port)} ({port})")
        if port > 65535 or port < 0:
            raise ValueError(f"Port must be within the allowed range (0-2^16), got {port}")


class JavaServer(MCServer):
    """Base class for a Minecraft Java Edition server."""

    def __init__(self, host: str, port: int = 25565, *, timeout: float = 3):
        """Override init to add a default port for java servers of 25565."""
        super().__init__(host, port, timeout=timeout)

    @classmethod
    def lookup(cls, address: str, timeout: float = 3) -> Self:
        """Parses the given address and checks DNS records for an SRV record that points to the Minecraft server.

        :param str address: The address of the Minecraft server, like `example.com:25565`.
        :param float timeout: The timeout in seconds before failing to connect.
        :return: A `MinecraftServer` instance.
        :rtype: MinecraftServer
        """

        host, port = cls.parse_address(address)
        if port is None:
            port = 25565
            try:
                answers = dns.resolver.resolve("_minecraft._tcp." + host, RdataType.SRV)
                if len(answers):
                    answer = answers[0]
                    host = str(answer.target).rstrip(".")
                    port = int(answer.port)
            except Exception:
                pass

        return cls(host, port, timeout=timeout)

    def ping(self, **kwargs) -> float:
        """Checks the latency between a Minecraft Java Edition server and the client (you).

        :param type **kwargs: Passed to a `ServerPinger` instance.
        :return: The latency between the Minecraft Server and you.
        :rtype: float
        """

        connection = TCPSocketConnection((self.host, self.port), self.timeout)
        return self._retry_ping(connection, **kwargs)

    @retry(tries=3)
    def _retry_ping(self, connection: TCPSocketConnection, **kwargs) -> float:
        pinger = ServerPinger(connection, host=self.host, port=self.port, **kwargs)
        pinger.handshake()
        return pinger.test_ping()

    async def async_ping(self, **kwargs) -> float:
        """Asynchronously checks the latency between a Minecraft Java Edition server and the client (you).

        :param type **kwargs: Passed to a `AsyncServerPinger` instance.
        :return: The latency between the Minecraft Server and you.
        :rtype: float
        """

        connection = TCPAsyncSocketConnection()
        await connection.connect((self.host, self.port), self.timeout)
        return await self._retry_async_ping(connection, **kwargs)

    @retry(tries=3)
    async def _retry_async_ping(self, connection: TCPAsyncSocketConnection, **kwargs) -> float:
        pinger = AsyncServerPinger(connection, host=self.host, port=self.port, **kwargs)
        pinger.handshake()
        ping = await pinger.test_ping()
        return ping

    def status(self, **kwargs) -> PingResponse:
        """Checks the status of a Minecraft Java Edition server via the ping protocol.

        :param type **kwargs: Passed to a `ServerPinger` instance.
        :return: Status information in a `PingResponse` instance.
        :rtype: PingResponse
        """

        connection = TCPSocketConnection((self.host, self.port), self.timeout)
        return self._retry_status(connection, **kwargs)

    @retry(tries=3)
    def _retry_status(self, connection: TCPSocketConnection, **kwargs) -> PingResponse:
        pinger = ServerPinger(connection, host=self.host, port=self.port, **kwargs)
        pinger.handshake()
        result = pinger.read_status()
        result.latency = pinger.test_ping()
        return result

    async def async_status(self, **kwargs) -> PingResponse:
        """Asynchronously checks the status of a Minecraft Java Edition server via the ping protocol.

        :param type **kwargs: Passed to a `AsyncServerPinger` instance.
        :return: Status information in a `PingResponse` instance.
        :rtype: PingResponse
        """

        connection = TCPAsyncSocketConnection()
        await connection.connect((self.host, self.port), self.timeout)
        return await self._retry_async_status(connection, **kwargs)

    @retry(tries=3)
    async def _retry_async_status(self, connection: TCPAsyncSocketConnection, **kwargs) -> PingResponse:
        pinger = AsyncServerPinger(connection, host=self.host, port=self.port, **kwargs)
        pinger.handshake()
        result = await pinger.read_status()
        result.latency = await pinger.test_ping()
        return result

    def query(self) -> QueryResponse:
        """Checks the status of a Minecraft Java Edition server via the query protocol.

        :return: Query status information in a `QueryResponse` instance.
        :rtype: QueryResponse
        """
        host = self.host
        try:
            answers = dns.resolver.resolve(host, RdataType.A)
            if len(answers):
                answer = answers[0]
                host = str(answer).rstrip(".")
        except DNSException:
            pass

        return self._retry_query(host)

    @retry(tries=3)
    def _retry_query(self, host: str) -> QueryResponse:
        connection = UDPSocketConnection((host, self.port), self.timeout)
        querier = ServerQuerier(connection)
        querier.handshake()
        return querier.read_query()

    async def async_query(self) -> QueryResponse:
        """Asynchronously checks the status of a Minecraft Java Edition server via the query protocol.

        :return: Query status information in a `QueryResponse` instance.
        :rtype: QueryResponse
        """
        host = self.host
        try:
            answers = dns.resolver.resolve(host, RdataType.A)
            if len(answers):
                answer = answers[0]
                host = str(answer).rstrip(".")
        except DNSException:
            pass

        return await self._retry_async_query(host)

    @retry(tries=3)
    async def _retry_async_query(self, host) -> QueryResponse:
        connection = UDPAsyncSocketConnection()
        await connection.connect((host, self.port), self.timeout)
        querier = AsyncServerQuerier(connection)
        await querier.handshake()
        return await querier.read_query()


class BedrockServer(MCServer):
    """Base class for a Minecraft Bedrock Edition server."""

    def __init__(self, host: str, port: int = 19139, *, timeout: float = 3):
        """Override init to add a default port for bedrock servers of 19139."""
        super().__init__(host, port, timeout=timeout)

    @classmethod
    def lookup(cls, address: str) -> Self:
        """Parses a given address and returns a BedrockServer instance.

        :param str address: The address of the Minecraft server, like `example.com:19132`
        :return: A `MinecraftBedrockServer` instance.
        :rtype: MinecraftBedrockServer
        """
        host, port = cls.parse_address(address)
        # If the address didn't contain port, fall back to constructor's default
        if port is None:
            return cls(host)
        return cls(host, port)

    @retry(tries=3)
    def status(self, **kwargs) -> BedrockStatusResponse:
        """Checks the status of a Minecraft Bedrock Edition server.

        :param type **kwargs: Passed to a `BedrockServerStatus` instance.
        :return: Status information in a `BedrockStatusResponse` instance.
        :rtype: BedrockStatusResponse
        """
        return BedrockServerStatus(self.host, self.port, self.timeout, **kwargs).read_status()

    @retry(tries=3)
    async def async_status(self, **kwargs) -> BedrockStatusResponse:
        """Asynchronously checks the status of a Minecraft Bedrock Edition server.

        :param type **kwargs: Passed to a `BedrockServerStatus` instance.
        :return: Status information in a `BedrockStatusResponse` instance.
        :rtype: BedrockStatusResponse
        """
        return await BedrockServerStatus(self.host, self.port, self.timeout, **kwargs).read_status_async()


@deprecated(replacement="JavaServer", date="2022-08", methods=("__init__",))
class MinecraftServer(JavaServer):
    """This is a deprecated version of the base class for a Java Minecraft Server.

    This class is kept purely for backwards compatibility reasons and will be removed eventually.
    """

    def __init__(self, host: str, port: int = 25565, timeout: float = 3):
        super().__init__(host, port=port, timeout=timeout)


@deprecated(replacement="BedrockServer", date="2022-08", methods=("__init__",))
class MinecraftBedrockServer(BedrockServer):
    """This is a deprecated version of the base class for a Bedrock Minecraft Server.

    This class is kept purely for backwards compatibility reasons and will be removed eventually.
    """

    def __init__(self, host: str, port: int = 19139, timeout: float = 3):
        super().__init__(host, port=port, timeout=timeout)
