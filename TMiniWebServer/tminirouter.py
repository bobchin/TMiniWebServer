from json import dumps, loads

from . import logging
from .tminiwebserver_util import TMiniWebServerUtil

LOGGER = logging.getLogger(__name__)

# クライアントとの接続を扱うクラス
class TMiniRouter:

    # コンストラクタ
    def __init__(self, req, res, route_args):
        self.request = req
        self.response = res
        self.route_params = route_args
        self.query_params = req._query_params
        self.form_params = req._form_params

    # json形式のリクエストを取得する
    async def read_json(self):
        try:
            data = await self.request.read_content()
            return loads(data.decode())
        except:
            pass
        return None

    # json形式のリクエストを書き込む
    async def write_json(self, data):
        if not isinstance(data, str):
            data = dumps(data)
        await self.response.write_response(content = data, content_type = "application/json")

    # データを書き込む
    async def write(self, content, **args):
        keys = ["headers", "http_status", "content_type", "content_charset"]
        args = dict(filter(lambda item: item[0] in keys, args.items()))
        await self.response.write_response(content, **args)
