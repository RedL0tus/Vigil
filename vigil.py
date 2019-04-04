#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os
import yaml
import logging

from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types

ADMINS = [
    124616797
]

TOKEN = '815268806:AAEPiFvmhOBFwlBkCNY-RxGB7LB_klly0XA'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VigilStrings(object):
    ENABLED: str = '已在本群组启用'
    DISABLED: str = '已在本群组禁用'
    ADMIN_REQUIRED: str = '需要管理员权限'
    TITLE_ENABLED: str = '已启用自动修改群标题'
    TITLE_DISABLED: str = '已禁用自动修改群标题'
    TITLE_TEMPLATE_UPDATED: str = '群标题模板已更新到 "{template}"'
    TITLE_TEMPLATE_CURRENT: str = '当前群标题模板为 "{template}"'


class VigilGroup(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilGroup'

    def __init__(
            self, group_id: int,
            enabled: bool = False,
            timezone: str = 'Asia/Shanghai',
            title_enabled: bool = False,
            title_template: str = '椰树 {yeshu_year} 年第 {day} 届守夜大赛'
    ):
        self.id: int = group_id
        self.enabled: bool = enabled
        self.timezone: str = timezone
        self.title_enabled: bool = title_enabled
        self.title_template: str = title_template


class VigilBot(object):
    def __init__(self, token: str, admins: list, data_path: str = 'data.yaml'):
        self.id: int = int(TOKEN.split(':', maxsplit=1)[0])
        self.bot: Bot = Bot(token=token)
        self.dispatcher: Dispatcher = Dispatcher(self.bot)
        self.strings = VigilStrings()
        self.data_path: str = data_path
        self.admins = admins
        self.data: dict = dict()
        self.load_data()
        if not self.data:
            self.data = dict()
        if 'groups' not in self.data.keys():
            self.data['groups']: dict = dict()

    def load_data(self):
        if os.path.isfile(self.data_path):
            with open(self.data_path) as f:
                self.data = yaml.safe_load(f)
                logger.info('Data loaded from "%s"' % self.data_path)

    def dump_data(self):
        with open(self.data_path, 'w+') as f:
            yaml.safe_dump(self.data, f)
            logger.info('Data dumped to "%s"' % self.data_path)

    def add_group(self, group_id: int):
        if group_id >= 0:
            logger.info('Invalid group ID')
            return
        if group_id not in self.data['groups'].keys():
            self.data['groups'][group_id]: VigilGroup = VigilGroup(group_id)
            logger.info('Group with ID "%s" has been added' % group_id)
            self.dump_data()

    def get_group(self, group_id) -> VigilGroup or None:
        return self.data['groups'].get(group_id, None)

    def update_group(self, group: VigilGroup):
        if group.id in self.data['groups'].keys():
            self.data['groups'][group.id] = group
            logger.info('Group with ID "%s" has been updated' % group.id)
            self.dump_data()

    async def is_admin(self, group: VigilGroup):
        bot: types.ChatMember = await self.bot.get_chat_member(group.id, self.id)
        return bot.is_admin()

    async def is_valid(self, group: VigilGroup, message: types.Message):
        if not group:
            return False
        member: types.ChatMember = await self.bot.get_chat_member(group.id, message.from_user.id)
        return member.is_admin()

    async def handler_add_group(self, message: types.Message):
        if message.from_user.id in self.admins:
            group_id: int = int(message.text.split(' ', maxsplit=1)[1])
            self.add_group(group_id)

    async def handler_enable(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if (not group) and (message.from_user.id in self.admins):
            self.add_group(message.chat.id)
            group: VigilGroup = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if not group.enabled:
                group.enabled = True
                self.update_group(group)
                logger.info('Bot enabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.ENABLED)

    async def handler_disable(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if group.enabled:
                group.enabled = False
                self.update_group(group)
                logger.info('Bot disabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.DISABLED)

    async def handler_enable_title_update(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if not await self.is_admin(group):
                group.title_enabled = False
                self.update_group(group)
                await message.reply(self.strings.ADMIN_REQUIRED)
                return
            if not group.title_enabled:
                group.title_enabled = True
                self.update_group(group)
            await message.reply(self.strings.TITLE_ENABLED)

    async def handler_disable_title_update(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if group.title_enabled:
                group.title_enable = False
                self.update_group(group)
            await message.reply(self.strings.TITLE_DISABLED)

    async def handler_update_title_template(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            template: str = str(message.text.split(' ', maxsplit=1)[1])
            if template != group.title_template:
                group.title_template = template
                self.update_group(group)
            await message.reply(self.strings.TITLE_TEMPLATE_UPDATED.format(template=template))

    async def handler_current_title_template(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            await message.reply(self.strings.TITLE_TEMPLATE_CURRENT.format(template=group.title_template))

    def start(self):
        commands = [
            (['add_group'], self.handler_add_group),
            (['enable'], self.handler_enable),
            (['disable'], self.handler_disable),
            (['enable_title_update'], self.handler_enable_title_update),
            (['disable_title_update'], self.handler_disable_title_update),
            (['current_title_template'], self.handler_current_title_template)
        ]
        for command in commands:
            self.dispatcher.register_message_handler(command[1], commands=command[0])
            logger.info('Command "%s" registered' % command[0])
        executor.start_polling(self.dispatcher)


if __name__ == '__main__':
    vigil = VigilBot(TOKEN, ADMINS)
    vigil.start()
