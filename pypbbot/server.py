from __future__ import annotations

import typing

import psutil  # type: ignore

if typing.TYPE_CHECKING:
    from asyncio import Future
    from typing import Tuple, Optional, Type, Union
    from pypbbot.driver import Drivable
    from pypbbot.typing import ProtobufBotAPI

import asyncio
import os
import threading
import time
import uuid

import uvicorn  # type: ignore
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

import pypbbot.driver
import pypbbot.plugin
from pypbbot.logging import LOG_CONFIG, logger
from pypbbot.typing import ProtobufBotFrame as Frame
from pypbbot.utils import LRULimitedDict, in_lower_case


class PyPbBotApp(FastAPI):
    driver_builder: Optional[Type[pypbbot.driver.BaseDriver]] = None
    plugin_path: Optional[str] = None


app = PyPbBotApp()
loop = None
drivers: LRULimitedDict[int, Tuple[WebSocket, Drivable]] = LRULimitedDict()
resp_cache: LRULimitedDict[str,
                           Future[Optional[ProtobufBotAPI]]] = LRULimitedDict()
alive_clients: LRULimitedDict[str, int] = LRULimitedDict()


@ app.on_event("startup")
async def init() -> None:
    """Init all the plugins after preload.
    """
    global loop
    loop = asyncio.get_running_loop()
    if os.environ.get("PYPBBOT_PLUGIN_PATH") != None:
        app.plugin_path = os.environ.get("PYPBBOT_PLUGIN_PATH")
        # os.environ.unsetenv("PYPBBOT_PLUGIN_PATH")
    if type(app.plugin_path) is str:
        logger.info("Loading plugins form: [{}]".format(
            os.path.abspath(app.plugin_path)))
        await pypbbot.plugin.load_plugins(app.plugin_path)
    logger.info('Everything is almost ready. Hello, PyProtobufBot world!')


@ app.on_event("shutdown")
async def close() -> None:
    logger.info('Shutting down. Have a nice day!')


@ app.websocket("/shutdown")
async def handle_shutdown(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.warning("Being asked to shutdown by websocket trigger.")

    def self_terminate() -> None:
        asyncio.run(close())
        time.sleep(1)
        parent = psutil.Process(psutil.Process(os.getpid()).ppid())
        parent.kill()
    threading.Thread(target=self_terminate, daemon=True).start()


@ app.websocket("/pbbot")
async def handle_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    botId = int(websocket.headers.get("x-self-id"))
    logger.info('Accepted client [{}] from [{}:{}]'.format(
        botId, websocket.client.host, websocket.client.port))
    client_addr = "{}:{}".format(
        websocket.client.host, websocket.client.port)

    if not botId in drivers.keys():
        alive_clients[client_addr] = botId
        driver_builder = app.driver_builder
        if driver_builder is None:
            driver_builder = pypbbot.driver.BaseDriver
        drivers[botId] = (websocket, driver_builder(botId))
    else:
        _, dri = drivers[botId]
        drivers[botId] = (websocket, dri)

    while True:
        try:
            rawdata: bytes = await websocket.receive_bytes()
            frame = Frame()
            frame.ParseFromString(rawdata)
            await recv_frame(frame, botId)
        except WebSocketDisconnect:
            client_addr = "{}:{}".format(
                websocket.client.host, websocket.client.port)
            client_id: Union[str, int] = "UNKNOWN"
            if alive_clients[client_addr] != -1:
                client_id = alive_clients[client_addr]
                del drivers[client_id]
            logger.warning('Connection to [{}] has been closed, lost connection with [{}] '.format(
                client_addr, client_id))
            break


async def recv_frame(frame: Frame, botId: int) -> None:
    frame_type = Frame.FrameType.Name(frame.frame_type)
    logger.debug('Recv frame [{}] from client [{}]'.format(
        frame_type, frame.botId))
    _, driver = drivers[frame.botId]
    if frame_type.endswith('Event'):
        event = getattr(frame, frame.WhichOneof('data'))
        if isinstance(driver, pypbbot.driver.BaseDriver):
            asyncio.create_task(driver.handle(event))
    else:
        if frame.echo in resp_cache.keys():
            if isinstance(frame.WhichOneof('data'), str):
                resp_cache[frame.echo].set_result(
                    getattr(frame, frame.WhichOneof('data')))
            else:
                resp_cache[frame.echo].set_result(None)


async def send_frame(botId: int, api_content: ProtobufBotAPI) -> Optional[ProtobufBotAPI]:
    frame = Frame()
    ws, _ = drivers[botId]
    frame.botId, frame.echo, frame.ok = botId, str(uuid.uuid1()), True
    frame.frame_type = getattr(
        Frame.FrameType, 'T' + type(api_content).__name__)
    getattr(frame, in_lower_case(
        type(api_content).__name__)).CopyFrom(api_content)
    data = frame.SerializeToString()
    frame_type = Frame.FrameType.Name(frame.frame_type)
    logger.debug('Send frame [{}] to client [{}]'.format(
        frame_type, frame.botId))
    await ws.send_bytes(data)
    resp_cache[frame.echo] = asyncio.get_event_loop().create_future()

    try:
        retv = await asyncio.wait_for(resp_cache[frame.echo], 60)
    except asyncio.TimeoutError:
        logger.error('Timed out for frame [{}]'.format(frame.echo))
        retv = None
    finally:
        resp_cache.remove(frame.echo)
    return retv


def run_server(**kwargs):  # type: ignore
    uvicorn.run(loop="asyncio", log_config=LOG_CONFIG, **kwargs)
