import uasyncio as asyncio
import sys
import re
import gc
import binascii
import hashlib
from json import loads, dumps
from .tminiwebserver_util import TMiniWebServerUtil, HttpStatusCode

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
    debug = 0
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
        def websocket_decorator(func):
            item = (url_path, 'websocket', func)
            cls._decorate_route_handlers.append(item)
            return func
        return websocket_decorator

    @staticmethod
    def log(message):
        print(f"[log] {message}")

    @staticmethod
    def dlog(message):
        if TMiniWebServer.debug == 1:
            print(f"[debug] {message}")

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
            route_parts = url_path.split('/')
            route_arg_names = [ ]
            route_regex = ''
            for s in route_parts:
                # <> で囲われている場合は、名称で置換する
                if s.startswith('<') and s.endswith('>'):
                    route_arg_names.append(s[1:-1])
                    route_regex += '/(\\w*)'
                elif s:
                    route_regex += '/' + s
            route_regex += '$'
            TMiniWebServer.dlog(f"  url_path:{url_path} -> regex: {route_regex}")
            route_regex = re.compile(route_regex)
            self._route_handlers.append(_WebServerRoute(url_path, method.upper(), func, route_arg_names, route_regex))
            TMiniWebServer.dlog(f'route add: {url_path}, {route_arg_names}')

    # サーバを開始
    async def start(self):
        if self.is_started():
            return
        server = await asyncio.start_server(self._server_proc, host=self._server_ip, port=self._server_port, backlog = 5)
        self._server = server
        self._running = True
        TMiniWebServer.log(f'start server on {self._server_ip}:{self._server_port}')

    # サーバを停止
    def stop(self):
        if not self.is_started():
            return
        if self._server is not None:
            try:
                self._server.close()
            except:
                pass
            self._running = False

    # 実行中かどうか
    def is_started(self):
        return self._running

    # ルートハンドラを検索する
    # url_path: ルートパス
    # method  : HTTPメソッド
    # return: (ハンドラメソッド, キーのハッシュ)
    def _get_route_handler(self, url_path, method):
        TMiniWebServer.dlog(f'search {url_path},{method}')
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
            print(f"  {url_path}, {method}")
            return (None, None)

    # サーバメイン処理
    async def _server_proc(self, reader, writer):
        addr = ''
        try:
            addr = writer.get_extra_info('peername')
            TMiniWebServer.log(f"connected by {addr}")
            client = TMiniWebClient(reader, writer, self)
            if not await client._processRequest():
                TMiniWebServer.log(f'process request failed. {addr}')
        except Exception as e:
            TMiniWebServer.log(e)

        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        TMiniWebServer.dlog(f"webclient is terminated. [{addr}]")

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
        mime_type = TMiniWebServerUtil.get_minetype_from_ext(file_path)
        return file_path, mime_type


class TMiniWebClient:

    # コンストラクタ
    # reader: クライアントからの読み込みストリーム？
    # writer: クライアントへの書き出しストリーム？
    # server: TMiniWebServerインスタンス
    def __init__(self, reader, writer, server):
        self._reader = reader
        self._writer = writer
        self._server = server
        self._method = None
        self._req_path = '/'
        self._path = None
        self._headers = { }
        self._content_type = None
        self._content_length = 0
        self._query_string = ""
        self._query_params = { }

    # クライアントと切断する
    async def close(self):
        self._writer.close()
        await self._writer.wait_closed()

    # クライアントへ応答する
    # content: HTTPの内容
    # headers: HTTPのヘッダ
    # http_status: HTTPのステータス
    # content_type:
    # content_charset:
    async def write_response(self, content, headers={}, http_status = HttpStatusCode.OK, content_type="text/html", content_charset='UTF-8'):
        TMiniWebServer.dlog('[in] write_response')
        try:
            if content:
                if type(content) == str:
                    content = content.encode(content_charset)
                content_length = len(content)
            else:
                content_length = 0

            # HTTPの書き込み
            # ステータスコード+ヘッダ+コンテンツ
            self._write_status_code(http_status)
            self._write_headers(headers, content_type, content_charset, content_length)
            await self._writer.drain()

            self._writer.write(content)
            await self._writer.drain()
        except Exception as ex:
            TMiniWebServer.log(ex)
            pass
        TMiniWebServer.dlog('[out] write_response')

    # クライアントへファイルの内容を返す
    # file_phys_path: ファイルのパス
    async def write_response_from_file(self, file_phys_path, headers={}, http_status = HttpStatusCode.OK, content_type=None, content_charset='UTF-8'):
        TMiniWebServer.dlog('[in] write_response_from_file')
        try:
            if not TMiniWebServerUtil.is_exist_file(file_phys_path):
                await self.write_error_response(HttpStatusCode.NOT_FOUND)
                return
            if content_type is None:
                content_type = TMiniWebServerUtil.get_minetype_from_ext(file_phys_path)

            content_length = TMiniWebServerUtil.get_file_size(file_phys_path)
            self._write_status_code(http_status)
            self._write_headers(headers, content_type, content_charset, content_length)
            await self._writer.drain()

            if content_length > 0:
                with open(file_phys_path, 'rb') as f:
                    while True:
                        data = f.read(4*1024)
                        if len(data) > 0:
                            self._writer.write(data)
                            await self._writer.drain()
                        else:
                            break
            if TMiniWebServer.gc_after_filesend:
                gc.collect()
        except Exception as ex:
            sys.print_exception(ex)

        TMiniWebServer.dlog('[out] write_response_from_file')

    # エラーを返す
    async def write_error_response(self, code, content=None):
        if content is None:
            content = HttpStatusCode.messages.get(code, '')
        TMiniWebServer.dlog(content)
        await self.write_response(http_status=code, content=content)

    # リクエストを読み込む
    async def read_request_content(self):
        try:
            data = await self._reader.read(self._content_length)
            return data
        except:
            pass
        return b''

    # json形式のリクエストを読み込む
    async def read_request_json_content(self):
        try:
            data = await self.read_request_content()
            return loads(data.decode())
        except:
            pass
        return None

    async def get_www_form_urlencoded(self):
        result = { }
        try:
            if self._content_type:
                params = self._content_type.lower().split(';')
                if params[0].strip() == 'application/x-www-form-urlencoded':
                    data = await self.read_request_content()
                    if data:
                        elements = data.decode().split('&')
                        for s in elements:
                            param = s.split('=', 1)
                            if len(param) > 0:
                                value = TMiniWebServerUtil.unquote_plus(param[1]) if len(param) > 1 else ''
                                result[TMiniWebServerUtil.unquote_plus(param[0])] = value
        except:
            pass
        TMiniWebServer.dlog(f'www-form-urlencoded: {result}')
        return result

    # ステータスコードの出力
    # ex) HTTP/1.1 404 Not Found
    def _write_status_code(self, status_code):
        msg = HttpStatusCode.messages.get(status_code, '')
        data = f"HTTP/1.1 {status_code} {msg}\r\n"
        self._writer.write(data)

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

    # ヘッダの出力
    def _write_headers(self, headers, content_type, content_charset, content_length):
        if isinstance(headers, dict):
            for header in headers:
                self._write_header(header, headers[header])
        self._write_header("server", "TMiniWebServer")
        self._write_header("connection", "close")
        if content_length > 0:
            self._write_content_type_header(content_type, content_charset)
            self._write_header('content-length', content_length)
        self._writer.write("\r\n")

    # クライアントのリクエスト処理
    async def _processRequest(self):
        if await self._parse():
            if await self._parse_header():
                is_upg = self._check_upgrade()
                if not is_upg:
                    return await self._routing_http()
                else:
                    ## WebSocket
                    if is_upg == 'websocket':
                        return await self._routing_websocket()
                    else:
                        await self._write_bad_request()
            else:
                await self._write_bad_request()
        else:
            await self._write_internal_server_error()
        return False

    # リクエスト内容の解析
    # _query_string と _query_params に格納する
    async def _parse(self):
        try:
            readline = await self._reader.readline()
            line = readline.decode().strip()
            elements = line.split()
            if len(elements) == 3:
                self._method = elements[0].upper()
                self._path = elements[1]
                self._http_ver = elements[2].upper()
                elements = self._path.split('?', 1)

                if len(elements) > 0:
                    self._req_path = TMiniWebServerUtil.unquote_plus(elements[0]) 
                    if len(elements) > 1:
                        self._query_string = elements[1]
                        elements = self._query_string.split('&')
                        for s in elements:
                            param = s.split('=', 1)
                            if len(param) > 0:
                                value = TMiniWebServerUtil.unquote(param[1]) if len(param) > 1 else ''
                                self._query_params[TMiniWebServerUtil.unquote(param[0])] = value
                        TMiniWebServer.dlog(f'{self} query_string:{self._query_string}')
                        TMiniWebServer.dlog(f'{self} query_params:{self._query_params}')
                return True
            else:
                TMiniWebServer.dlog("failed read first line (httprequest)")
                return False

            return True
        except Exception as ex:
            TMiniWebServer.log(ex)
        return False

    # ヘッダの解析
    # _headers に格納
    async def _parse_header(self):
        while True:
            elements = (await self._reader.readline()).decode().strip().split(':', 1)
            if len(elements) == 2:
                self._headers[elements[0].strip().lower()] = elements[1].strip()
            elif len(elements) == 1 and len(elements[0]) == 0:
                if self._method == 'POST' or self._method == 'PUT':
                    self._content_type = self._headers.get("content-type", None)
                    self._content_length = (int)(self._headers.get('content-length', 0))

                TMiniWebServer.dlog(f"headers={self._headers}")
                return True
            else:
                TMiniWebServer.log(f"_parse_header warning: {elements}")
                return False

    # upgrade ヘッダを確認する
    def _check_upgrade(self):
        if 'upgrade' in self._headers.get('connection', '').lower():
            return self._headers.get('upgrade', '').lower()
        return None

    # 400 エラーを返す
    async def _write_bad_request(self):
        await self.write_error_response(HttpStatusCode.BAD_REQUEST)

    # 500 エラーを返す
    async def _write_internal_server_error(self):
        await self.write_error_response(HttpStatusCode.INTERNAL_SERVER_ERROR)

    # 通常のHTTP通信処理
    async def _routing_http(self):
        TMiniWebServer.dlog('in _routing_http')
        route, route_args = self._server._get_route_handler(self._req_path, self._method)
        if self._method is None:
            print(self._req_path)
            print(self._path)
            print(self._headers)

        result = False
        # 登録された処理がある場合は、デコレータを実行
        if route:
            TMiniWebServer.dlog(f'found route: {self._req_path}, args: {route_args}')
            try:
                if route_args is not None:
                    await route(self, route_args)
                else:
                    await route(self)
                result = True
            except Exception as ex:
                TMiniWebServer.dlog(f"in _routeing_http: {ex}")
        # 登録された処理がない場合
        else:
            TMiniWebServer.dlog('routing is not found.')
            # GET 処理の場合はファイルを探してあれば返す
            if self._method.upper() == 'GET':
                TMiniWebServer.dlog(f'search static files [{self._server._wwwroot}]')
                file_phys_path, mime_type = self._server.get_phys_path_in_wwwroot(self._req_path)

                if file_phys_path is None:
                    await self.write_error_response(HttpStatusCode.NOT_FOUND)
                    TMiniWebServer.log(f'fild not found [{self._req_path}]')
                else:
                    TMiniWebServer.dlog(f'file found [{mime_type}, {file_phys_path}]')
                    await self.write_response_from_file(file_phys_path, content_type=mime_type)

                result = True ## メソッドの処理結果としては正常の処理.

            # GET以外はエラー
            else:
                await self._write_bad_request()
                result = True ## メソッドの処理結果としては正常の処理としておく.
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception as ex:
            sys.print_exception(ex)
            pass
        return result

    # WebSocket通信処理
    async def _routing_websocket(self):
        TMiniWebServer.dlog('in _routing_websocket')
        route, route_args = self._server._get_route_handler(self._req_path, 'websocket')
        if not route:
            TMiniWebServer.dlog(f'not found websocket route. [{self._req_path}]')
            await self._write_bad_request()
            return True

        websocket = TMiniWebSocket(self)
        try:
            if await websocket.handshake() == False:
                TMiniWebServer.dlog('handshake failed.')
                return True
        except:
            return False

        try:
            TMiniWebServer.dlog(f'found route: {self._req_path}, args: {route_args}')
            if route_args:
                await route(websocket, route_args)
            else:
                await route(websocket)
        except Exception as ex:
            TMiniWebServer.log(ex)
            return False

        return True

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
                TMiniWebServer.log(f'WebSocket closed. (exception : {ex})')
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
            TMiniWebServer.log('Invalid WebSocket frame header')
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

