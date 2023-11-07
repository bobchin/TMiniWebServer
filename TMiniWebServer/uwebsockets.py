"""
Websockets protocol
"""
from micropython import const
from . import logging
import select
import ure as re
import ustruct as struct
import urandom as random
from ucollections import namedtuple

LOGGER = logging.getLogger(__name__)

# Opcodes
OP_CONT  = const(0x0)
OP_TEXT  = const(0x1)
OP_BYTES = const(0x2)
OP_CLOSE = const(0x8)
OP_PING  = const(0x9)
OP_PONG  = const(0xa)

# Close codes
CLOSE_OK                 = const(1000)
CLOSE_GOING_AWAY         = const(1001)
CLOSE_PROTOCOL_ERROR     = const(1002)
CLOSE_DATA_NOT_SUPPORTED = const(1003)
CLOSE_BAD_DATA           = const(1007)
CLOSE_POLICY_VIOLATION   = const(1008)
CLOSE_TOO_BIG            = const(1009)
CLOSE_MISSING_EXTN       = const(1010)
CLOSE_BAD_CONDITION      = const(1011)

URL_RE = re.compile(r'(wss|ws)://([A-Za-z0-9-\.]+)(?:\:([0-9]+))?(/.+)?')
URI = namedtuple('URI', ('protocol', 'hostname', 'port', 'path'))

class NoDataException(Exception):
    pass

class ConnectionClosed(Exception):
    pass

def urlparse(uri):
    """Parse ws:// URLs"""
    match = URL_RE.match(uri)
    if match:
        protocol = match.group(1)
        host = match.group(2)
        port = match.group(3)
        path = match.group(4)

        if protocol == 'wss':
            if port is None:
                port = 443
        elif protocol == 'ws':
            if port is None:
                port = 80
        else:
            raise ValueError('Scheme {} is invalid'.format(protocol))

        return URI(protocol, host, int(port), path)


class Websocket:
    """
    Basis of the Websocket protocol.
    """
    is_client = False

    def __init__(self, sock=None, reader=None, writer=None):
        self.sock = sock
        self.reader = reader
        self.writer = writer
        self.open = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # 指定時間処理をブロックする
    def settimeout(self, timeout):
        poller = select.poll()
        if self.sock:
            poller.register(self.sock, select.POLLIN)
        try:
            poller.poll(timeout * 1000)
        except:
            pass

    # バイトデータを読み込む
    async def _read(self, length):
        if self.sock:
            return self.sock.read(length)
        elif self.reader:
            return await self.reader.read(length)
        else:
            return b''

    # バイトデータを書き込む
    def _write(self, length):
        if self.sock:
            self.sock.write(length)
        elif self.writer:
            self.writer.write(length)
        else:
            pass

    # フレームを読み込む
    async def read_frame(self):
        """
        Read a frame from the socket.
        See https://tools.ietf.org/html/rfc6455#section-5.2 for the details.
        """
        LOGGER.debug("read_frame start")

        # Frame header
        two_bytes = await self._read(2)
        if not two_bytes:
            LOGGER.debug(f"two_bytes={two_bytes}")
            raise NoDataException

        byte1, byte2 = struct.unpack('!BB', two_bytes)[0:2]

        # Byte 1: FIN(1) _(1) _(1) _(1) OPCODE(4)
        fin = bool(byte1 & 0x80)
        opcode = byte1 & 0x0f
        LOGGER.debug(f"fin={fin}, opcode={opcode}")

        # Byte 2: MASK(1) LENGTH(7)
        mask = bool(byte2 & (1 << 7))
        length = byte2 & 0x7f
        LOGGER.debug(f"mask={mask}, length={length}")

        if length == 126:  # Magic number, length header is 2 bytes
            length, = struct.unpack('!H', await self._read(2))
        elif length == 127:  # Magic number, length header is 8 bytes
            length, = struct.unpack('!Q', await self._read(8))
        LOGGER.debug(f"length_ext={length}")

        # Mask is 4 bytes
        mask_bits = await self._read(4) if mask else b''
        LOGGER.debug(f"mask_bits={mask_bits}")

        try:
            data = await self._read(length)
        except MemoryError:
            # We can't receive this many bytes, close the socket
            LOGGER.debug("Frame of length %s too big. Closing", length)
            self.close(code=CLOSE_TOO_BIG)
            return True, OP_CLOSE, b''

        if mask:
            data = bytes(b ^ mask_bits[i % 4] for i, b in enumerate(data))

        return fin, opcode, data

    # フレームを書き出す
    def write_frame(self, opcode, data=b''):
        """
        Write a frame to the socket.
        See https://tools.ietf.org/html/rfc6455#section-5.2 for the details.
        """
        LOGGER.debug("write_frame start")
        fin = True
        mask = self.is_client  # messages sent by client are masked
        length = len(data)
        LOGGER.debug(f"fin={fin}, mask={mask}")
        LOGGER.debug(f"data={data}, length={length}")

        # Frame header
        # Byte 1: FIN(1) _(1) _(1) _(1) OPCODE(4)
        byte1 = 0x80 if fin else 0
        byte1 |= opcode

        # Byte 2: MASK(1) LENGTH(7)
        byte2 = 0x80 if mask else 0

        if length < 126:  # 126 is magic value to use 2-byte length header
            byte2 |= length
            self._write(struct.pack('!BB', byte1, byte2))

        elif length < (1 << 16):  # Length fits in 2-bytes
            byte2 |= 126  # Magic code
            self._write(struct.pack('!BBH', byte1, byte2, length))

        elif length < (1 << 64):
            byte2 |= 127  # Magic code
            self._write(struct.pack('!BBQ', byte1, byte2, length))

        else:
            raise ValueError()

        if mask:  # Mask is 4 bytes
            mask_bits = struct.pack('!I', random.getrandbits(32))
            self._write(mask_bits)

            data = bytes(b ^ mask_bits[i % 4] for i, b in enumerate(data))

        self._write(data)

    # データを受信する
    async def recv(self):
        """
        Receive data from the websocket.

        This is slightly different from 'websockets' in that it doesn't
        fire off a routine to process frames and put the data in a queue.
        If you don't call recv() sufficiently often you won't process control
        frames.
        """

        while self.open:
            try:
                fin, opcode, data = await self.read_frame()
                LOGGER.debug("recv: fin={fin}, opcode={opcode}, data={data}")
            except NoDataException:
                return ''
            except ValueError:
                LOGGER.debug("Failed to read frame. Socket dead.")
                self._close()
                raise ConnectionClosed()

            if not fin:
                raise NotImplementedError()

            if opcode == OP_TEXT:
                return data.decode('utf-8')
            elif opcode == OP_BYTES:
                return data
            elif opcode == OP_CLOSE:
                self._close()
                return
            elif opcode == OP_PONG:
                # Ignore this frame, keep waiting for a data frame
                continue
            elif opcode == OP_PING:
                # We need to send a pong frame
                LOGGER.debug("Sending PONG")
                self.write_frame(OP_PONG, data)
                # And then wait to receive
                continue
            elif opcode == OP_CONT:
                # This is a continuation of a previous frame
                raise NotImplementedError(opcode)
            else:
                raise ValueError(opcode)

    # データを送信する
    def send(self, buf):
        """Send data to the websocket."""

        if isinstance(buf, str):
            opcode = OP_TEXT
            buf = buf.encode('utf-8')
        elif isinstance(buf, bytes):
            opcode = OP_BYTES
        else:
            raise TypeError()

        self.write_frame(opcode, buf)

    # opcode を書き込んでソケットを閉じる
    def close(self, code=CLOSE_OK, reason=''):
        """Close the websocket."""
        if not self.open:
            return

        buf = struct.pack('!H', code) + reason.encode('utf-8')

        self.write_frame(OP_CLOSE, buf)
        self._close()

    # ソケットを閉じる
    def _close(self):
        LOGGER.debug("Connection closed")
        self.open = False
        if self.sock:
            self.sock.close()
