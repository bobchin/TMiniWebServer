from TMiniWebServer import TMiniWebServer
import sys

##-------------------------------------------------------------------------
## WebSocket の通信例
##-------------------------------------------------------------------------

@TMiniWebServer.with_websocket('/ws/<id>')
async def websockcet_handler(websocket):
    id = websocket.route_params['id']
    print(f"id: {id}")
    while not websocket.is_closed():
        try:
            data = await websocket.receive()
            print(f'received: {data}')
            if data == 'cmd_close':
                await websocket.close()
            else:
                await websocket.send("Hello,world!!")
            if data is None:
                print(f'disconnected.')
        except Exception as ex:
            sys.print_exception(ex)
    print(f"closed websocket (id: {id})")

@TMiniWebServer.with_websocket('/echo')
async def ws_echo_handler(websocket):
    print("websocket echo handler start")
    while not websocket.is_closed():
        try:
            data = await websocket.receive()
            print(f'received: {data}')
            await websocket.send(data)
        except Exception as ex:
            sys.print_exception(ex)
