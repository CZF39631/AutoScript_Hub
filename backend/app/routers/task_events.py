"""Python Agent 专用 WS 提示；禁止浏览器和 query 凭据。"""
import asyncio
from contextlib import suppress

import anyio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.services import task_notifications as notifications

router = APIRouter(tags=["tasks"])
SCAN_INTERVAL = 1.5
SYNC_INTERVAL = 30.0
SEND_TIMEOUT = 3.0
MAX_RECEIVE_BYTES = 1024
SYNC = {"type": "sync_required", "protocol": 1}


async def send(websocket, payload):
    await asyncio.wait_for(websocket.send_json(payload), timeout=SEND_TIMEOUT)


async def receive(websocket):
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        data = message.get("bytes")
        if (text is not None and len(text.encode("utf-8")) > MAX_RECEIVE_BYTES) or (
            data is not None and len(data) > MAX_RECEIVE_BYTES
        ):
            await asyncio.wait_for(websocket.close(code=1009), SEND_TIMEOUT)
            return
        # 客户端消息不触发数据库扫描或任务动作。
        await asyncio.sleep(0)


async def scan(websocket, device_id, token, device_token, factory, initial):
    previous = initial
    last_sync = asyncio.get_running_loop().time()
    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        current = await run_in_threadpool(
            notifications.snapshot, device_id, token, device_token, factory,
        )
        now = asyncio.get_running_loop().time()
        if current != previous or now - last_sync >= SYNC_INTERVAL:
            await send(websocket, SYNC)
            last_sync = now
        previous = current


@router.websocket("/api/task-devices/{device_id}/events")
async def task_events(websocket: WebSocket, device_id: int):
    authorization = websocket.headers.get("authorization", "").split()
    device_token = websocket.headers.get("x-device-token")
    if (websocket.scope.get("query_string") or "origin" in websocket.headers
            or len(authorization) != 2 or authorization[0].lower() != "bearer"
            or not device_token):
        await websocket.close(code=1008)
        return
    # 全进程配额也涵盖认证中的连接，避免握手造成无界 DB 工作。
    if not notifications.registry.acquire(device_id):
        await websocket.close(code=1013)
        return
    workers = []
    close_code = 1000
    try:
        factory = getattr(websocket.app.state, "task_notifications_session_factory", None)
        initial = await run_in_threadpool(
            notifications.snapshot, device_id, authorization[1], device_token, factory,
        )
        await asyncio.wait_for(websocket.accept(), SEND_TIMEOUT)
        await send(websocket, {"type": "ready", "protocol": 1})
        await send(websocket, SYNC)
        workers = [
            asyncio.create_task(receive(websocket)),
            asyncio.create_task(scan(websocket, device_id, authorization[1], device_token, factory, initial)),
        ]
        done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except HTTPException:
        close_code = 1008
    except (WebSocketDisconnect, OSError):
        pass
    except asyncio.TimeoutError:
        close_code = 1013
    except Exception:
        # 不把数据库异常、认证头或任何执行内容发给对端。
        close_code = 1011
    finally:
        for task in workers:
            task.cancel()
        notifications.registry.release(device_id)
        # ASGI/测试客户端可在断开时取消整个作用域；仍须回收子任务。
        with anyio.CancelScope(shield=True):
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            with suppress(Exception):
                await asyncio.wait_for(websocket.close(code=close_code), SEND_TIMEOUT)
