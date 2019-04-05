#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os
import pytz
import yaml
import logging

from aiogram import Bot, Dispatcher, executor, types
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

CONFIG_PATH = 'config.yaml'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VigilStrings(object):
    ID_INVALID: str = '{id} 为无效 ID'
    TOO_LESS_ARGUMENTS: str = '缺少参数'
    ADMIN_ADDED: str = '{id} 已被设为管理员'
    GROUP_ADDED: str = '已添加群组 {id}'
    ENABLED: str = '已在本群组启用'
    DISABLED: str = '已在本群组禁用'
    GROUP_STATUS: str = '''\
    群组 ID： {id}
    是否启用： {enabled}
    时区： {timezone}
    是否启用标题自动更新： {title_enabled}
    标题模板： "{title_template}"
    '''  # 格式化歪打正着
    TIMEZONE_CURRENT: str = '当前时区为 {timezone}'
    TIMEZONE_INVALID: str = '无效的时区'
    TIMEZONE_UPDATED: str = '时区已更新至 {timezone}'
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
        self.id: int = int(token.split(':', maxsplit=1)[0])
        self.bot: Bot = Bot(token=token)
        self.dispatcher: Dispatcher = Dispatcher(self.bot)
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler()
        self.strings = VigilStrings()
        self.data_path: str = data_path
        self.data: dict = dict()
        self.load_data()
        if not self.data:
            self.data = dict()
        if 'groups' not in self.data.keys():
            self.data['groups']: dict = dict()
        if 'admins' not in self.data.keys():
            self.data['admins']: list = list()
        self.data['admins']: list = list(set(self.data['admins'] + admins))
        self.dump_data()

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

    async def is_admin(self, group: VigilGroup) -> bool:
        bot: types.ChatMember = await self.bot.get_chat_member(group.id, self.id)
        return bot.is_admin()

    async def is_valid(self, group: VigilGroup, message: types.Message) -> bool:
        if not group:
            return False
        member: types.ChatMember = await self.bot.get_chat_member(group.id, message.from_user.id)
        return member.is_admin()

    async def update_title(self, group: VigilGroup):
        if group.title_enabled:
            if not await self.is_admin(group):
                group.title_enabled = False
                self.update_group(group)
                return
            timezone: pytz.timezone = pytz.timezone(group.timezone)
            localtime: datetime = datetime.utcnow().astimezone(timezone)
            await self.bot.set_chat_title(
                group.id,
                group.title_template.format(
                    yeshu_year=int(localtime.year - 1988),
                    day=int(localtime.timetuple().tm_yday)
                )
            )
            logger.info('Title updated for group with ID "%s"' % group.id)

    async def update_title_all(self):
        for group in self.data['groups'].values():
            await self.update_title(group)
        logger.info('All titles have been updated')

    async def handler_add_admin(self, message: types.Message):
        if message.from_user.id in self.data['admins']:
            try:
                ids = message.text.split(' ')[1:]
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            response: str = ''
            for single_id in ids:
                try:
                    if single_id not in self.data['admins']:
                        self.data['admins'].append(int(single_id))
                        self.dump_data()
                    response += str(self.strings.ADMIN_ADDED.format(id=str(single_id)) + '\n')
                except ValueError:
                    response += str(self.strings.ID_INVALID.format(id=str(single_id)) + '\n')
                    continue
            await message.reply(response)

    async def handler_add_group(self, message: types.Message):
        if message.from_user.id in self.data['admins']:
            try:
                group_id: int = int(message.text.split(' ', maxsplit=1)[1])
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            self.add_group(group_id)
            await message.reply(self.strings.GROUP_ADDED.format(id=group_id))

    async def handler_enable(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if (not group) and (message.from_user.id in self.data['admins']):
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

    async def handler_group_status(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            response: str = self.strings.GROUP_STATUS.format(
                id=str(group.id),
                enabled='是' if group.enabled else '否',
                timezone=str(group.timezone),
                title_enabled='是' if group.title_enabled else '否',
                title_template=str(group.title_template)
            )
            await message.reply(response)

    async def current_timezone(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            await message.reply(self.strings.TIMEZONE_CURRENT.format(timezone=group.timezone))

    async def handler_update_timezone(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            try:
                timezone: str = str(message.text.split(' ', maxsplit=1)[1])
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            if timezone not in pytz.all_timezones:
                await message.reply(self.strings.TIMEZONE_INVALID)
            group.timezone = timezone
            self.update_group(group)
            await self.update_title(group)
            await message.reply(self.strings.TIMEZONE_UPDATED.format(timezone=timezone))

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
            await self.update_title(group)
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
            try:
                template: str = str(message.text.split(' ', maxsplit=1)[1])
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            if template != group.title_template:
                group.title_template = template
                self.update_group(group)
            await self.update_title(group)
            await message.reply(self.strings.TITLE_TEMPLATE_UPDATED.format(template=template))

    async def handler_current_title_template(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            await message.reply(self.strings.TITLE_TEMPLATE_CURRENT.format(template=group.title_template))

    def start(self):
        commands = [
            (['add_admin'], self.handler_add_admin),
            (['add_group'], self.handler_add_group),
            (['enable'], self.handler_enable),
            (['disable'], self.handler_disable),
            (['group_status'], self.handler_group_status),
            (['current_timezone'], self.current_timezone),
            (['update_timezone'], self.handler_update_timezone),
            (['enable_title_update'], self.handler_enable_title_update),
            (['disable_title_update'], self.handler_disable_title_update),
            (['update_title_template'], self.handler_update_title_template),
            (['current_title_template'], self.handler_current_title_template)
        ]
        for command in commands:
            self.dispatcher.register_message_handler(command[1], commands=command[0])
            logger.info('Command "%s" registered' % command[0])
        self.scheduler.add_job(self.update_title_all, 'interval', hours=1, next_run_time=datetime.now())
        self.scheduler.start()
        executor.start_polling(self.dispatcher)


if __name__ == '__main__':
    from sys import argv
    import argparse
    import trafaret as t
    from trafaret_config import commandline

    validator: t.Dict = t.Dict({
        t.Key('token'): t.String,
        t.Key('admins'):
            t.List(t.Int())
    })

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    commandline.standard_argparse_options(
        parser,
        default_config=CONFIG_PATH
    )

    options, unknown = parser.parse_known_args(argv)
    config: dict = commandline.config_from_options(options, validator)

    vigil: VigilBot = VigilBot(config['token'], config['admins'])
    vigil.start()
