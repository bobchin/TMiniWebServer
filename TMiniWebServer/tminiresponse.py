import sys
import gc
from . import logging
from .tminiwebserver_util import TMiniWebServerUtil, HttpStatusCode

LOGGER = logging.getLogger(__name__)

class TMiniResponse:

    # コンストラクタ
    # writer: クライアントへの書き出しストリーム？
    # server: TMiniWebServerインスタンス
    def __init__(self, writer):
        self._writer = writer

    # クライアントへ応答する
    # content: HTTPの内容
    # headers: HTTPのヘッダ
    # http_status: HTTPのステータス
    # content_type: メディアタイプ
    # content_charset: 文字コード
    async def write_response(self, content, headers={}, http_status = HttpStatusCode.OK, content_type="text/html", content_charset='UTF-8'):
        LOGGER.debug('[in] write_response')
        try:
            content_length = 0
            if content:
                if type(content) == str:
                    content = content.encode(content_charset)
                content_length = len(content)

            # HTTPの書き込み
            # ステータスコード+ヘッダ+コンテンツ
            self._write_status_code(http_status)
            self._write_headers(headers, content_type, content_charset, content_length)
            await self._writer.drain()
            self._writer.write(content)
            await self._writer.drain()
        except Exception as ex:
            LOGGER.error(ex)
            pass
        LOGGER.debug('[out] write_response')

    # クライアントへファイルの内容を返す
    # file_phys_path: ファイルのパス
    # headers: HTTPのヘッダ
    # http_status: HTTPのステータス
    # content_type: メディアタイプ
    # content_charset: 文字コード
    async def write_response_from_file(self, file_phys_path, headers={}, http_status = HttpStatusCode.OK, content_type=None, content_charset='UTF-8'):
        LOGGER.debug('[in] write_response_from_file')
        try:
            # ファイルが存在しない => NOT_FOUND
            if not TMiniWebServerUtil.is_exist_file(file_phys_path):
                await self.write_error_response(HttpStatusCode.NOT_FOUND)
                return

            # ファイルの拡張子からMIME-Typeを取得
            if content_type is None:
                content_type = TMiniWebServerUtil.get_minetype_from_ext(file_phys_path)

            # ファイルサイズを取得
            content_length = TMiniWebServerUtil.get_file_size(file_phys_path)

            # HTTPの書き込み
            # ステータスコード+ヘッダ
            self._write_status_code(http_status)
            self._write_headers(headers, content_type, content_charset, content_length)
            await self._writer.drain()

            # 内容の書き込み
            if content_length > 0:
                with open(file_phys_path, 'rb') as f:
                    while True:
                        data = f.read(4*1024)
                        if len(data) > 0:
                            self._writer.write(data)
                            await self._writer.drain()
                        else:
                            break

            gc.collect()
        except Exception as ex:
            sys.print_exception(ex)

        LOGGER.debug('[out] write_response_from_file')

    # エラーを返す
    # code: HTTPステータスコード
    # content: 指定しない場合は、エラー簡易メッセージを表示
    async def write_error_response(self, code, content=None):
        if content is None:
            content = HttpStatusCode.messages.get(code, '')
        LOGGER.debug(content)
        await self.write_response(http_status=code, content=content)
        return False

    async def write_bad_request(self):
        await self.write_error_response(HttpStatusCode.BAD_REQUEST)

    # ステータスコードの出力
    # ex) HTTP/1.1 404 Not Found
    def _write_status_code(self, status_code):
        msg = HttpStatusCode.messages.get(status_code, '')
        data = f"HTTP/1.1 {status_code} {msg}\r\n"
        self._writer.write(data)

    # ヘッダの出力
    def _write_headers(self, headers, content_type, content_charset, content_length):
        if isinstance(headers, dict):
            map(lambda x: self._write_header(x[0], x[1]), headers.items())
        self._write_header("server", "TMiniWebServer")
        self._write_header("connection", "close")
        if content_length > 0:
            self._write_content_type_header(content_type, content_charset)
            self._write_header('content-length', content_length)
        self._writer.write("\r\n")

    # ヘッダの出力
    # ex) Content-Type application/json; charset=UTF-8
    def _write_header(self, name, value):
        self._writer.write(f"{name}: {value}\r\n")

    # content-typeヘッダの書き込み
    # content_typeが指定されない場合: content-type application/octet-stream
    # content-typeが指定された場合: content-type application/json | Content-Type application/json; charset=UTF-8
    def _write_content_type_header(self, content_type, charset = None):
        ct = "application/octet-stream"
        if content_type:
            ct = content_type + ((f"; charset={charset}") if charset else "")
        self._write_header('content-type', ct)

    # クライアントと切断する
    async def close(self):
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception as ex:
            sys.print_exception(ex)
