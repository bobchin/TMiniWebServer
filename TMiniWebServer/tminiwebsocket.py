import binascii
import hashlib
from . import logging
from .tminiwebserver_util import HttpStatusCode
from .tminirouter import TMiniRouter
from .uwebsockets import Websocket

LOGGER = logging.getLogger(__name__)

# WebSocket通信処理をするクラス
class TMiniWebSocket(TMiniRouter):
    @classmethod
    async def factory(cls, req, res, args):
        websocket = TMiniWebSocket(req, res, args)
        if await websocket.handshake() == False:
            LOGGER.debug('handshake failed.')
        return websocket

    # コンストラクタ
    def __init__(self, req, res, args):
        super().__init__(req, res, args)
        self._websocket = Websocket(reader=req._reader, writer=res._writer)

    # 切断しているかどうか
    def is_closed(self):
        return not self._websocket.open

    # 切断する
    async def close(self):
        self._websocket.close()

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
                return await self._websocket.recv()
            except Exception as ex:
                LOGGER.error(f'WebSocket closed. (exception : {ex})')
                return None
        return None

    # クライアントにデータを送信する
    # data:
    # type:
    def send(self, data):
        self._websocket.send(data)

    # webscoket コネクション確立の応答を返す
    #
    # HTTP/1.1 101 OK
    # Upgrade: websocket
    # Connection: upgrade
    # Sec-Websocket-Accept: xxxx
    async def _send_upgrade_response(self, key):
        self.response._write_status_code(HttpStatusCode.SWITCH_PROTOCOLS)
        self.response._write_header('upgrade', 'websocket')
        self.response._write_header('connection', 'upgrade')
        self.response._write_header('sec-websocket-accept', self._res_key(key))
        await self.response._drain("\r\n")

    # RFC 6455 Sec-WebSocket-Accept
    # Sec-Websocket-Key ヘッダ値の末尾に
    # "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" を足して
    # SHA-1 でハッシュ値にし、base64でエンコードする
    def _res_key(self, websocket_key):
        d = hashlib.sha1(websocket_key.encode())
        d.update(b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
        return binascii.b2a_base64(d.digest())[:-1].decode()

