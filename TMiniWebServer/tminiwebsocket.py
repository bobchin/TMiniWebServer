import binascii
import hashlib
import sys
from . import logging
from .tminiwebserver_util import HttpStatusCode
from .tminirouter import TMiniRouter

LOGGER = logging.getLogger(__name__)

# WebSocket通信処理をするクラス
class TMiniWebSocket(TMiniRouter):
    class Opcode:
        CONTINUE = 0
        TEXT = 1
        BINARY = 2
        CLOSE = 8
        PING = 9
        PONG = 10

    # コンストラクタ
    def __init__(self, req, res, args):
        super().__init__(req, res, args)
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

    # websocket のコネクション確立する
    async def handshake(self):
        websocket_key = self.request._headers.get('sec-websocket-key', None)
        if websocket_key is None:
            self.response.write_bad_request()
            return False

        await self._send_upgrade_response(websocket_key)
        return True

    # クライアントから受信する
    # return:
    #  data: データ
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
                    return data
            except Exception as ex:
                self._closed = True
                LOGGER.error(f'WebSocket closed. (exception : {ex})')
                return None
        return None

    # クライアントにデータを送信する
    # data:
    # type:
    async def send(self, data, opcode = None):
        if not opcode:
            opcode = self.Opcode.TEXT if isinstance(data, str) else self.Opcode.BINARY
        await self._send_core(opcode, data)

    # RFC 6455 Sec-WebSocket-Accept
    # Sec-Websocket-Key ヘッダ値の末尾に
    # "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" を足して
    # SHA-1 でハッシュ値にし、base64でエンコードする
    def _create_response_key(self, websocket_key):
        d = hashlib.sha1(websocket_key.encode())
        d.update(b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
        return binascii.b2a_base64(d.digest())[:-1].decode()

    # webscoket コネクション確立の応答を返す
    #
    # HTTP/1.1 101 OK
    # Upgrade: websocket
    # Connection: upgrade
    # Sec-Websocket-Accept: xxxx
    async def _send_upgrade_response(self, websocket_key):
        response_key = self._create_response_key(websocket_key)

        self.response._write_status_code(HttpStatusCode.SWITCH_PROTOCOLS)
        self.response._write_header('upgrade', 'websocket')
        self.response._write_header('connection', 'upgrade')
        self.response._write_header('sec-websocket-accept', response_key)
        self.response._writer.write("\r\n")
        await self.response._writer.drain()

    # フレームを書き込む
    async def _send_core(self, opcode, payload):
        if self.is_closed():
            return
        try:
            frame = bytearray()
            # 1バイト目
            # Fin = 1, RSV1,2,3 = 0 は固定
            frame.append(0x80 | int(opcode))
            if opcode == self.Opcode.TEXT:
                payload = payload.encode()

            # 2バイト目
            # 最上位1ビットのMASK値は0だが、length <= 127 なので0になる。
            payload_length = len(payload)
            if payload_length < 126:
                # 126 バイトより小さい場合はそのまま
                frame.append(payload_length)
            elif payload_length < (1 << 16):
                # 126 バイト以上 65535 = 2^16 バイト以下の場合は
                # 126+2ビットで長さ指定
                frame.append(126)
                frame.extend(payload_length.to_bytes(2, 'big'))
            else:
                # それ以外は、127+8ビットで長さ指定
                frame.append(127)
                frame.extend(payload_length.to_bytes(8, 'big'))

            # データ
            frame.extend(payload)
            self.response._writer.write(frame)
            await self.response._writer.drain()
        except OSError as ex:
            if ex.errno == 104: ## ECONNREST
                self._closed = True
            return
        except Exception as ex:
            sys.print_exception(ex)

    # フレームを読み込む
    async def _read_frame(self):
        header = await self.request._reader.read(2)
        if len(header) != 2:
            LOGGER.info('Invalid WebSocket frame header')
            raise OSError(32, 'WebSocket connection closed')

        ## ヘッダのパース
        _, opcode, has_mask, length = self._parse_frame_header(header)
        if length < 0:
            length = await self.request._reader.read(length * -1)
            length = int.from_bytes(length, 'big')
        LOGGER.debug(f"opcode: {opcode}")
        LOGGER.debug(f"has_mask: {has_mask}")
        LOGGER.debug(f"length: {length}")

        mask = await self.request._reader.read(4) if has_mask else None
        LOGGER.debug(f"mask: 0x{mask.hex().upper() if mask else 'None'}")
        payload = await self.request._reader.read(length)
        if mask:
            payload = bytes(x ^ mask[i % 4] for i, x, in enumerate(payload))
        return opcode, payload

    # フレームヘッダを解析する
    def _parse_frame_header(self, header):
        # header[0] = FIN(1)+RSV1(1)+RSV2(1)+RSV3(1)+OPCODE(4)
        # header[1] = MASK(1)+PAYLOAD LEN(7)
        fin = header[0] & 0x80
        opcode = header[0] & 0x0F
        has_mask = header[1] & 0x80
        length = header[1] & 0x7F
        # 126 の場合は2バイト、127 の場合は8バイト読み込む
        if length == 126:
            length = -2
        elif length == 127:
            length = -8
        return fin, opcode, has_mask, length

    # フレームを種別毎に処理する
    # opcode: データの種類
    # payload: データ
    def _process_frame(self, opcode, payload):
        res_opcode = None
        if opcode == self.Opcode.TEXT:
            payload = payload.decode()
        elif opcode == self.Opcode.BINARY:
            pass
        elif opcode == self.Opcode.CLOSE:
            self._closed = True
            payload = None
        elif opcode == self.Opcode.PING:
            res_opcode = self.Opcode.PONG
        elif opcode == self.Opcode.PONG:
            payload = None
        return res_opcode, payload
