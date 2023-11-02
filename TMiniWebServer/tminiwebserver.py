import uasyncio as asyncio
import sys
import re

from . import logging
from .tminiclient import TMiniWebClient
from .tminiwebserver_util import TMiniWebServerUtil

LOGGER = logging.getLogger(__name__)

# ルート毎の処理
class _WebServerRoute:
    # コンストラクタ
    # route          : デコレータで指定されたルート名
    # method         : HTTPメソッド(大文字)
    # func           : 処理内容
    # route_arg_names: 置換するキーのリスト
    # routeRegex     : <>指定された場合に置換するための正規表現
    def __init__(self, route, method, func, route_arg_names, routeRegex):
        self.route = route
        self.method = method
        self.func = func
        self.route_arg_names = route_arg_names
        self.route_regex = routeRegex

# WebServer
class TMiniWebServer:
    # デコレータで登録された処理のリスト
    _decorate_route_handlers = []

    gc_after_filesend = 1   ## ファイル送信後にGC発動しておくためのフラグ.

    # デコレータ
    # URL毎の処理を登録する
    # url_path: URLのパス
    # method  : HTTPメソッド
    @classmethod
    def route(cls, url_path, method='GET'):
        def route_decorator(func):
            item = (url_path, method, func)
            cls._decorate_route_handlers.append(item)
            return func
        return route_decorator

    # デコレータ
    # WebSocket処理を登録する
    # url_path: URLのパス
    @classmethod
    def with_websocket(cls, url_path):
        return cls.route(url_path, 'websocket')

    # コンストラクタ
    # port   : Webサーバのポート
    # bindIP : バインドするIPアドレス
    # wwwroot: 静的ファイルを置くディレクトリ
    def __init__(self, port = 80, bindIP = '0.0.0.0', wwwroot = '/wwwroot'):
        self._server_ip = bindIP
        self._server_port = port
        self._wwwroot = wwwroot
        self._running = False
        self._route_handlers = []
        self._add_route_item(self._decorate_route_handlers)

    # _route_handlers を構築する
    # source_decorators: デコレータで登録した処理タプルのリスト
    def _add_route_item(self, source_decorators):
        for url_path, method, func in source_decorators:
            # <> で囲われている場合は、正規表現で置換する
            regex_list = ['/(\\w*)' if s.startswith('<') and s.endswith('>') else '/' + s for s in url_path.split('/') if s]
            route_str = ''.join(regex_list) + '$'
            route_regex = re.compile(route_str)
            LOGGER.debug(f"  url_path: {url_path} -> regex: {route_str}")

            route_arg_names = [s[1:-1] for s in url_path.split('/') if s.startswith('<') and s.endswith('>')]
            self._route_handlers.append(_WebServerRoute(url_path, method.upper(), func, route_arg_names, route_regex))
            LOGGER.debug(f'route add : {url_path}, {route_arg_names}')

    # サーバを開始
    async def start(self):
        if self.is_started():
            return

        self._server = await asyncio.start_server(self._server_proc, host=self._server_ip, port=self._server_port, backlog = 5)
        self._running = True
        LOGGER.info(f'start server on {self._server_ip}:{self._server_port}')

    # サーバを停止
    def stop(self):
        if not self.is_started():
            return
        if self._server is None:
            return

        try:
            self._server.close()
        except:
            pass
        self._running = False
        LOGGER.info(f'stop server')

    # 実行中かどうか
    def is_started(self):
        return self._running

    # ルートハンドラを検索する
    # url_path: ルートパス
    # method  : HTTPメソッド
    # return: (ハンドラメソッド, キーのハッシュ)
    def _get_route_handler(self, url_path, method):
        LOGGER.debug(f'search {url_path},{method}')
        try:
            # ルートハンドラが登録されているか
            if not self._route_handlers:
                return (None, None)

            url_path = url_path.rstrip('/')
            method = method.upper()

            # 登録されているルートハンドラからURLが対応するものを抽出
            filterd_handlers = [h for h in self._route_handlers if h.method == method and h.route_regex.match(url_path)]
            if len(filterd_handlers) == 0:
                return (None, None)

            handler = filterd_handlers[0]
            if handler.route_arg_names and (m := handler.route_regex.match(url_path)):
                # <xxx> で指定された部分を辞書化する
                values = m.groups()
                values = list(map(lambda s: int(s) if s.isdigit() else s, values))
                route_args = dict(zip(handler.route_arg_names, values))
            else:
                route_args = None
            return (handler.func, route_args)

        except Exception as ex:
            sys.print_exception(ex)
            LOGGER.error(f"  {url_path}, {method}")
            return (None, None)

    # サーバメイン処理
    async def _server_proc(self, reader, writer):
        addr = ''
        try:
            addr = writer.get_extra_info('peername')
            LOGGER.info(f"connected by {addr}")

            client = TMiniWebClient(reader, writer, self)
            if not await client._processRequest():
                LOGGER.info(f'process request failed. {addr}')
        except Exception as e:
            LOGGER.error(e)

        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        LOGGER.debug(f"webclient is terminated. [{addr}]")

    # wwwroot のパスを取得する
    # request_path: リクエストされたパス
    def get_phys_path_in_wwwroot(self, request_path):
        file_path = ''
        exist_file = False

        # ルート指定以外の場合は、指定されたファイルを探す
        if request_path != '/':
            file_path = self._wwwroot + '/' + request_path
            exist_file = TMiniWebServerUtil.is_exist_file(file_path)

        # ルート指定の場合は、'index.html' or 'index.htm' を探す
        else:
            for file_name in ['index.html', 'index.htm']:
                file_path = self._wwwroot + '/' + file_name
                exist_file = TMiniWebServerUtil.is_exist_file(file_path)
                if exist_file:
                    break

        if not exist_file:
            return None, None
        else:
            mime_type = TMiniWebServerUtil.get_minetype_from_ext(file_path)
            LOGGER.debug(f'get static file. path:{file_path} type:{mime_type}')
            return file_path, mime_type
