import json
from channels.generic.websocket import AsyncWebsocketConsumer

class SeatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.showtime_id = self.scope['url_route']['kwargs']['showtime_id']
        self.room_group_name = f'seats_{self.showtime_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        action = text_data_json.get('action')
        seat_id = text_data_json.get('seat_id')

        # Broadcast the seat update to the group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'seat_update',
                'action': action,
                'seat_id': seat_id
            }
        )

    # Receive message from room group
    async def seat_update(self, event):
        action = event['action']
        seat_id = event['seat_id']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'action': action,
            'seat_id': seat_id
        }))
