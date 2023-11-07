from . import logging
from .tminiwebserver_util import TMiniWebServerUtil, HttpStatusCode

LOGGER = logging.getLogger(__name__)

class TMiniRequest:

    # コンストラクタ
    # reader: クライアントからの読み込みストリーム？
    def __init__(self, reader):
        self._reader = reader
        self._method = ""           # HTTP メソッド
        self._path = ""             # リクエストパス全体
        self._http_ver = ""         # HTTP バージョン
        self._req_path = '/'        # パス
        self._query_string = ""     # クエリー文字列
        self._query_params = { }    # クエリー文字列を辞書化
        self._headers = { }
        self._content_type = None
        self._content_length = 0
        self._form_params = { }

    async def parse(self):
        # ヘッダのリクエストラインを解析
        if not await self._parse():
            return False, HttpStatusCode.INTERNAL_SERVER_ERROR

        # ヘッダ全体を解析
        if not await self._parse_header():
            return False, HttpStatusCode.BAD_REQUEST

        # フォームパラメータの解析
        await self._parse_form_params()

        return True, None

    # リクエスト内容の解析
    # _query_string と _query_params に格納する
    async def _parse(self):
        try:
            # 1行読み込む
            elements = (await self._reader.readline()).decode().strip().split()
            if len(elements) != 3:
                LOGGER.debug("failed read first line (httprequest)")
                return False

            self._method = elements[0].upper()
            self._path = elements[1]
            self._http_ver = elements[2].upper()
            LOGGER.debug(f'method:{self._method}')
            LOGGER.debug(f'path:{self._path}')
            LOGGER.debug(f'httpver:{self._http_ver}')

            # パスとクエリーの取得
            elements = self._path.split('?', 1)
            self._req_path = TMiniWebServerUtil.unquote_plus(elements[0])
            LOGGER.debug(f'req_path:{self._req_path}')

            if len(elements) > 1:
                self._query_string = elements[1]
                for s in self._query_string.split('&'):
                    param = [TMiniWebServerUtil.unquote(p) for p in s.split('=', 1)]
                    self._query_params[param[0]] = param[1] if len(param) > 1 else ''

                LOGGER.debug(f'query_string:{self._query_string}')
                LOGGER.debug(f'query_params:{self._query_params}')
            return True

        except Exception as ex:
            LOGGER.error(ex)
            return False

    # ヘッダの解析
    # _headers に格納
    async def _parse_header(self):
        while True:
            elements = (await self._reader.readline()).decode().strip().split(':', 1)
            # ヘッダーを格納
            if len(elements) == 2:
                self._headers[elements[0].strip().lower()] = elements[1].strip()
                LOGGER.debug(f"header:{elements[0].strip().lower()}={elements[1].strip()}")
            # コンテンツ前の改行
            elif len(elements) == 1 and len(elements[0]) == 0:
                if self._method == 'POST' or self._method == 'PUT':
                    self._content_type = self._headers.get("content-type", None)
                    self._content_length = (int)(self._headers.get('content-length', 0))

                return True
            else:
                LOGGER.info(f"_parse_header warning: {elements}")
                return False

    # connection ヘッダが指定されている場合に upgrade ヘッダを返す
    # connection = upgrade かつ upgrade = websocket の場合、websocket にアップグレードする
    def check_upgrade(self):
        if 'upgrade' in self._headers.get('connection', '').lower():
            return self._headers.get('upgrade', '').lower()
        return None

    def get(self):
        return self._req_path, self._method

    def _is_form_urlencoded(self):
        if not self._content_type:
            LOGGER.debug("_is_form_urlencoded: content_type not found")
            return False

        params = self._content_type.lower().split(';')
        return params[0].strip() == 'application/x-www-form-urlencoded'

    # FORM形式のリクエストを取得する
    async def _parse_form_params(self):
        try:
            if self._is_form_urlencoded() == False:
                return

            data = await self.read_content()
            if not data:
                LOGGER.debug("form_params: content not found")
                return

            for s in data.decode().split('&'):
                param = [TMiniWebServerUtil.unquote_plus(p) for p in s.split('=', 1)]
                param.append('')
                self._form_params[param[0]] = param[1]
            LOGGER.debug(f"form_params: {self._form_params}")
            return
        except:
            return

    async def read_content(self):
        try:
            return await self._reader.read(self._content_length)
        except:
            return b''
