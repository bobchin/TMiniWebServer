from TMiniWebServer import TMiniWebServer
from json import dumps

##-------------------------------------------------------------------------
## REST API 向け
##-------------------------------------------------------------------------
@TMiniWebServer.route('/article/<id>', method='GET')
async def restapi_article_get(router):
    json_data = f'{{ "id": {router.route_params["id"]}, "message": "これは本文のテキストです。" }}'
    await router.write_json(json_data)

@TMiniWebServer.route('/article/<id>', method='PUT')
async def restapi_article_put(router):
    data = await router.read_json()
    html = f"""<html>
    <body>
        <p>ID: {router.route_params['id']}に対して、以下のデータで更新します。</p>
        <pre>
            {data}
        </pre>
    </body>
    </html>
    """
    await router.write(html)

@TMiniWebServer.route('/article', method='POST')
async def restapi_article_post(router):
    data = await router.read_json()
    res_obj = {
        'status' : 'OK',
        'id': 12345,
        'message': data['text']
    }
    await router.write_json(res_obj)

