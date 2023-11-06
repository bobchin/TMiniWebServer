from TMiniWebServer import TMiniWebServer, logging

import uasyncio as asyncio
import gc

import route.sample_basic
import route.sample_restapi
import route.sample_websocket

from machine import Pin

# logging.basicConfig(level=logging.WARNING)

## LED
led = Pin(25, Pin.OUT)

## Webサーバ
async def webserver():
    webserver = TMiniWebServer()
    await webserver.start()
    print('TMiniWebServer started.')

## LEDの定期点滅
async def blink_led():
    WAIT_SEC = 0.5
    while True:
        led.on()
        await asyncio.sleep(WAIT_SEC)
        led.off()
        await asyncio.sleep(WAIT_SEC)

## ガベージコレクション
async def garbage_collection():
    while True:
        print(f'free memory: {gc.mem_free()}')
        await asyncio.sleep(60)
        gc.collect()

## メイン
async def main():
    led_task = asyncio.create_task(blink_led())
    gc_task = asyncio.create_task(garbage_collection())
    sv_task = asyncio.create_task(webserver())

    await led_task
    await gc_task
    await sv_task

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
