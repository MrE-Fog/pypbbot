from __future__ import annotations

import typing

from pypbbot.plugin import _handlers

if typing.TYPE_CHECKING:
    from typing import Type, Dict, Optional, Tuple
    from pypbbot.typing import ProtobufBotAPI, Event, PrivateMessageEvent, GroupMessageEvent, ProtobufBotEvent

import inspect
from typing import Any, Callable, Union

from pypbbot import server
from pypbbot.affairs import BaseAffair, ChatAffair
from pypbbot.logging import logger
from pypbbot.protocol import *
from pypbbot.utils import Clips, SingletonType, sendBackClipsTo


class BaseDriver:
    def __init__(self, botId: int):
        self.botId = botId
        self._handler_registry: Dict[Type[ProtobufBotEvent], Callable[[
            ProtobufBotEvent], Any]] = {}
        self._handler_registry[PrivateMessageEvent] = getattr(
            self, 'onPrivateMessage')
        self._handler_registry[GroupMessageEvent] = getattr(
            self, 'onGroupMessage')
        self._handler_registry[GroupUploadNoticeEvent] = getattr(
            self, 'onGroupUploadNotice')
        self._handler_registry[GroupAdminNoticeEvent] = getattr(
            self, 'onGroupAdminNotice')
        self._handler_registry[GroupDecreaseNoticeEvent] = getattr(
            self, 'onGroupDecreaseNotice')
        self._handler_registry[GroupIncreaseNoticeEvent] = getattr(
            self, 'onGroupIncreaseNotice')
        self._handler_registry[GroupBanNoticeEvent] = getattr(
            self, 'onGroupBanNotice')
        self._handler_registry[FriendAddNoticeEvent] = getattr(
            self, 'onFriendAddNotice')
        self._handler_registry[GroupRecallNoticeEvent] = getattr(
            self, 'onGroupRecallNotice')
        self._handler_registry[FriendRecallNoticeEvent] = getattr(
            self, 'onFriendRecallNotice')
        self._handler_registry[FriendRequestEvent] = getattr(
            self, 'onFriendRequest')
        self._handler_registry[GroupRequestEvent] = getattr(
            self, 'onGroupRequest')

    async def handle(self, event: ProtobufBotEvent) -> None:
        if type(event) in self._handler_registry.keys():
            if inspect.iscoroutinefunction(self._handler_registry[type(event)]):
                await self._handler_registry[type(event)](event)
            else:
                self._handler_registry[type(event)](event)

    async def sendBackClips(self, event: Union[PrivateMessageEvent, GroupMessageEvent],
                            clips: Union[Clips, str, int, float]) -> Optional[ProtobufBotAPI]:
        return await sendBackClipsTo(event, clips)

    def onPrivateMessage(self, event: PrivateMessageEvent) -> Any:
        pass

    def onGroupMessage(self, event: GroupMessageEvent) -> Any:
        pass

    def onGroupUploadNotice(self, event: GroupUploadNoticeEvent) -> Any:
        pass

    def onGroupAdminNotice(self, event: GroupAdminNoticeEvent) -> Any:
        pass

    def onGroupDecreaseNotice(self, event: GroupDecreaseNoticeEvent) -> Any:
        pass

    def onGroupIncreaseNotice(self, event: GroupIncreaseNoticeEvent) -> Any:
        pass

    def onGroupBanNotice(self, event: GroupBanNoticeEvent) -> Any:
        pass

    def onFriendAddNotice(self, event: FriendAddNoticeEvent) -> Any:
        pass

    def onGroupRecallNotice(self, event: GroupRecallNoticeEvent) -> Any:
        pass

    def onFriendRecallNotice(self, event: FriendRecallNoticeEvent) -> Any:
        pass

    def onFriendRequest(self, event: FriendRequestEvent) -> Any:
        pass

    def onGroupRequest(self, event: GroupRequestEvent) -> Any:
        pass

    async def sendPrivateClips(self, user_id: int, clips: Union[Clips, str, int, float]) -> Optional[ProtobufBotAPI]:
        clips = Clips() + clips
        api_content = SendPrivateMsgReq()
        api_content.user_id, api_content.auto_escape = user_id, True
        api_content.message.extend(clips.toMessageList())
        return await server.send_frame(self.botId, api_content)

    async def sendGroupClips(self, group_id: int, clips: Union[Clips, str, int, float]) -> Optional[ProtobufBotAPI]:
        clips = Clips() + clips
        api_content = SendGroupMsgReq()
        api_content.group_id, api_content.auto_escape = group_id, True
        api_content.message.extend(clips.toMessageList())
        return await server.send_frame(self.botId, api_content)

    async def recallMessage(self, message_id: int) -> Optional[ProtobufBotAPI]:
        api_content = DeleteMsgReq()
        api_content.message_id = message_id
        return await server.send_frame(self.botId, api_content)


Drivable = BaseDriver


class AffairDriver(BaseDriver, metaclass=SingletonType):
    def __init__(self) -> None:
        pass

    def __new__(cls, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> Any:
        return object.__new__(cls)

    async def handle(self, event: Event) -> None:
        affair: BaseAffair
        if isinstance(event, PrivateMessageEvent) or isinstance(event, GroupMessageEvent):
            affair = ChatAffair(event)
        else:
            affair = BaseAffair(event)
        logger.warning('Handling [{}]'.format(affair))
        for handler in _handlers.queue:
            affair_filter = handler._ftr
            if affair_filter(affair):
                await handler._func(affair)
