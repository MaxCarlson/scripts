"""
WebSocket Connection Manager
Manages WebSocket connections and broadcasts updates to clients
"""
import logging
from typing import List, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.task_subscriptions: dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Remove from all task subscriptions
        for task_id, subscribers in self.task_subscriptions.items():
            if websocket in subscribers:
                subscribers.remove(websocket)

        logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for connection in dead_connections:
            self.disconnect(connection)

    async def send_to_task_subscribers(self, task_id: str, message: dict):
        """Send message to clients subscribed to a specific task"""
        if task_id not in self.task_subscriptions:
            return

        dead_connections = []

        for connection in self.task_subscriptions[task_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to task subscriber: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for connection in dead_connections:
            self.disconnect(connection)

    def subscribe_to_task(self, websocket: WebSocket, task_id: str):
        """Subscribe a client to updates for a specific task"""
        if task_id not in self.task_subscriptions:
            self.task_subscriptions[task_id] = set()

        self.task_subscriptions[task_id].add(websocket)
        logger.debug(f"Client subscribed to task {task_id}")

    def unsubscribe_from_task(self, websocket: WebSocket, task_id: str):
        """Unsubscribe a client from task updates"""
        if task_id in self.task_subscriptions:
            self.task_subscriptions[task_id].discard(websocket)
            logger.debug(f"Client unsubscribed from task {task_id}")
