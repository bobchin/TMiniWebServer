from TMiniWebServer import TMiniWebServer, HttpStatusCode

##-------------------------------------------------------------------------
## 基本形
##-------------------------------------------------------------------------
@TMiniWebServer.route('/simple')
async def webHandlerTest(router):
    data = 'Hello,world'

    ## ステータスコードは明示的に設定が可能で、省略時にはOK(200)が設定されている.
    ## レスポンスヘッダに追加の情報を与えることが可能.
    await router.write(data, http_status=HttpStatusCode.OK, headers={'myheader': 'sample_value'})

@TMiniWebServer.route('/sample/<id>/<kind>')
async def test_get_with_path_params(router):
   html = f"""<html lang='ja'>
   <body><p>パラメータ情報: <br/>
   id: {router.route_params['id']}<br/>
   kind: {router.route_params['kind']}</p></body>
   querys: {router.query_params}
   </html>"""
   await router.write(html)

@TMiniWebServer.route('/recvpost', method='POST')
async def recv_form_data(router):
    html = f"""<html lang='ja'>
    <body><p>送信データは {router.form_params['username']} です</p></body>
    </html>
    """
    await router.write(html)

