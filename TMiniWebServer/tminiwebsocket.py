import binascii
import hashlib
from . import logging
from .tminiwebserver_util import HttpStatusCode

LOGGER = logging.getLogger(__name__)

# WebSocket通信処理をするクラス
class TMiniWebSocket:
    class Opcode:
        CONTINUE = 0
        TEXT = 1
        BINARY = 2
        CLOSE = 8
        PING = 9
        PONG = 10
    class MessageType:
        TEXT = 1
        BINARY = 2

    # コンストラクタ
    def __init__(self, client):
        self._client = client
        self._closed = False
        pass

    # 切断しているかどうか
    def is_closed(self):
        return self._closed

    # 切断する
    async def close(self):
        try:
            await self._send_core(self.Opcode.CLOSE, b'')
        except:
            pass
        self._closed = True

    async def handshake(self):
        websocket_key = self._client._headers.get('sec-websocket-key', None)
        if websocket_key is None:
            self._client._write_bad_request()
            return False
        else:
            d = hashlib.sha1(websocket_key.encode())
            d.update(b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
            response_key = binascii.b2a_base64(d.digest())[:-1].decode()
            await self._send_upgrade_response(response_key)
            return True

    async def receive(self):
        while not self.is_closed():
            try:
                opcode, payload = await self._read_frame()
                send_opcode, data = self._process_frame(opcode, payload)
                if self.is_closed():
                    continue

                if send_opcode:
                    await self._send_core(send_opcode, data)
                elif data:
                    if opcode == self.Opcode.BINARY:
                        return data, self.MessageType.BINARY
                    elif opcode == self.Opcode.TEXT:
                        return data, self.MessageType.TEXT
            except Exception as ex:
                self._closed = True
                LOGGER.error(f'WebSocket closed. (exception : {ex})')
                return None, None
        return None, None

    async def send(self, data, type = MessageType.TEXT):
        if type == self.MessageType.TEXT:
            await self._send_core(self.Opcode.TEXT, data)
        if type == self.MessageType.BINARY:
            await self._send_core(self.Opcode.BINARY, data)

    async def _send_upgrade_response(self, response_key):
        self._client._write_status_code(HttpStatusCode.SWITCH_PROTOCOLS)
        self._client._write_header('upgrade', 'websocket')
        self._client._write_header('connection', 'upgrade')
        self._client._write_header('sec-websocket-accept', response_key)
        self._client._writer.write("\r\n")
        await self._client._writer.drain()

    async def _send_core(self, opcode, payload):
        if self.is_closed():
            return
        try:
            frame = bytearray()
            frame.append(0x80 | int(opcode))
            if opcode == self.Opcode.TEXT:
                payload = payload.encode()

            payload_length = len(payload)
            if payload_length < 126:
                frame.append(payload_length)
            elif payload_length < (1 << 16):
                frame.append(126)
                frame.extend(payload_length.to_bytes(2, 'big'))
            else:
                frame.append(127)
                frame.extend(payload_length.to_bytes(8, 'big'))
            frame.extend(payload)
            self._client._writer.write(frame)
            await self._client._writer.drain()
        except OSError as ex:
            if ex.errno == 104: ## ECONNREST
                self._closed = True
            return
        except Exception as ex:
            sys.print_exception(ex)

    async def _read_frame(self):
        header = await self._client._reader.read(2)
        if len(header) != 2:
            LOGGER.info('Invalid WebSocket frame header')
            raise OSError(32, 'WebSocket connection closed')
        ## ヘッダのパース.
        fin = header[0] & 0x80 > 0
        opcode = header[0] & 0x0F
        has_mask = header[1] & 0x80 > 0
        length = header[1] & 0x7F

        if length < 0:
            length = await self._client._reader.read(-length)
            length = int.from_bytes(length, 'big')
        if has_mask:
            mask = await self._client._reader.read(4)
        payload = await self._client._reader.read(length)
        if has_mask:
            payload = bytes( x ^ mask[i % 4] for i, x, in enumerate(payload))
        return opcode, payload

    def _process_frame(self, opcode, payload):
        if opcode == self.Opcode.TEXT:
            payload = payload.decode()
        elif opcode == self.Opcode.BINARY:
            pass
        elif opcode == self.Opcode.CLOSE:
            self._closed = True
            pass
        elif opcode == self.Opcode.PING:
            return self.Opcode.PONG, payload
        elif opcode == self.Opcode.PONG:
            return None, None
        return None, payload
