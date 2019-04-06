#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os
import pytz
import yaml
import logging

from aiogram import Bot, Dispatcher, executor, types
from datetime import datetime, timedelta
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
    是否启用广播： {broadcast_enabled}
    裁判模式： {mode}
    指定时间： {deadline}
    '''  # 格式化歪打正着
    STATUS_BROADCAST: str = '{timezone} 赛区还有 {number} 人参赛'
    STATUS_EMPTY: str = '无人参赛，你们太弱了'
    BROADCAST_ENABLED: str = '已启用广播'
    BROADCAST_DISABLED: str = '已禁用广播'
    TIMEZONE_CURRENT: str = '当前时区为 {timezone}'
    TIMEZONE_INVALID: str = '无效的时区'
    TIMEZONE_UPDATED: str = '时区已更新至 {timezone}'
    ADMIN_REQUIRED: str = '需要管理员权限'
    TITLE_ENABLED: str = '已启用自动修改群标题'
    TITLE_DISABLED: str = '已禁用自动修改群标题'
    TITLE_TEMPLATE_UPDATED: str = '群标题模板已更新到 "{template}"'
    TITLE_TEMPLATE_CURRENT: str = '当前群标题模板为 "{template}"'
    MODE_UPDATED: str = '模式已更新至 {mode}'
    MODE_INVALID: str = '不存在此模式'
    DEADLINE_UPDATED: str = '已更新至 {deadline}'
    DEADLINE_INVALID: str = '无效的时间，必须是个整数'
    JOINED: str = '已加入 {timezone} 场次'
    QUIT: str = '已退出本届大赛'
    AUTO_JOIN_ENABLED: str = '已设置自动加入 {timezone} 场次'
    AUTO_JOIN_DISABLED: str = '已取消自动加入'
    WINNER_FOUND: str = '本届大赛 {timezone} 场次的冠军是 {user}'


class VigilMode(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilMode'

    LAST: int = 0  # Last active user at a given time wins
    NO_ACTIVITY: int = 1  # Quit when no activity for a given time

    def __init__(self, mode: int):
        self.mode: int = mode


class VigilUser(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilUser'

    def __init__(
            self, user_id: int,
            active: datetime,
            joined: bool = True,
            timezone: str = 'Asia/Shanghai',
            is_dummy: bool = False,
    ):
        self.id: int = user_id
        self.joined: bool = joined
        self.timezone: str = timezone
        self.active_time: list = list()
        self.active_time.append(active)
        self.is_dummy: bool = is_dummy


class VigilWinner(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilWinner'

    def __init__(self, user: VigilUser, broadcasted: bool = False):
        self.id: int = user.id
        self.last_online: datetime = user.active_time[len(user.active_time) - 1]
        self.broadcasted: bool = broadcasted


class VigilGroup(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilGroup'

    def __init__(
            self, group_id: int,
            enabled: bool = False,
            timezone: str = 'Asia/Shanghai',
            title_enabled: bool = False,
            title_template: str = '椰树 {yeshu_year} 年第 {day} 届守夜大赛',
            mode: VigilMode = VigilMode(VigilMode.LAST),
            deadline: int = 6,
            broadcast_status: bool = False
    ):
        self.id: int = group_id
        self.enabled: bool = enabled
        self.timezone: str = timezone
        self.title_enabled: bool = title_enabled
        self.title_template: str = title_template
        self.auto_join: dict = dict()
        self.hall: dict = dict()
        self.mode: VigilMode = mode
        self.deadline: int = deadline
        self.winners: dict = dict()
        self.broadcast_status = broadcast_status

    def get_user(self, user_id) -> VigilUser:
        return self.hall.get(user_id, None)

    def update_hall(self, user: VigilUser):
        logger.info('Information of user with ID "%s" updated' % user.id)
        self.hall[user.id] = user

    def update_winner(self, date: str, timezone: str, winner: VigilWinner):
        logger.info('Information of winner with ID "%s" updated' % winner.id)
        if not self.winners.get(date, None):
            self.winners[date]: dict = dict()
        self.winners[date][timezone] = winner

    def search_winner_record(self, timezone: str, date: str) -> VigilUser or None:
        if type(self.winners[date]) != dict:
            return None
        winner: VigilWinner or None = self.winners[date].get(timezone, None)
        return winner

    @staticmethod
    def find_user_with_timezone(user_dict, timezone) -> list:
        result: list = list()
        for user in user_dict.values():
            if user.timezone == timezone:
                result.append(user)
        return result

    def clean_up_hall(self, timezone):
        remove_list: list = self.find_user_with_timezone(self.hall, timezone)
        for user_id in remove_list:
            try:
                del self.hall[user_id]
            except KeyError:
                pass

    def apply_auto_join(self, timezone):
        user_list: list = self.find_user_with_timezone(self.auto_join, timezone)
        for user in user_list:
            user.active_time = list()
            user.active_time.append(datetime.utcnow())
            if user.id not in self.hall.keys():
                self.hall[user.id] = user

    def find_winner(self):
        if not self.enabled:
            return
        if len(self.hall) < 1:
            return
        utc_time: datetime = datetime.utcnow()
        day_string: str = utc_time.strftime('%Y/%m/%d')
        for timezone in pytz.all_timezones:
            tz: pytz.timezone = pytz.timezone(timezone)
            localized_time: datetime = pytz.utc.localize(utc_time, is_dst=None).astimezone(tz)
            if self.mode.mode == VigilMode.LAST:
                if (localized_time.hour == self.deadline) and (localized_time.minute in range(1)):
                    if self.deadline not in range(24):
                        return
                    last_user: VigilUser = VigilUser(0, datetime(1070, 1, 1), is_dummy=True)  # Dummy user
                    for user in self.find_user_with_timezone(self.hall, timezone):
                        if user.active_time[len(user.active_time) - 1] >\
                                last_user.active_time[len(last_user.active_time) - 1]:
                            last_user = user
                    if last_user.is_dummy:
                        continue
                    self.update_winner(day_string, timezone, VigilWinner(last_user))
                    self.clean_up_hall(timezone)
                    if len(self.hall) == 0:
                        self.apply_auto_join(timezone)
            if self.mode.mode == VigilMode.NO_ACTIVITY:
                if (localized_time.hour > 0) and (localized_time.hour < 6):
                    users_left = self.find_user_with_timezone(self.hall, timezone)
                    remove_list: list = list()
                    for user in users_left:
                        if user.active_time[len(user.active_time) - 1] + timedelta(minutes=self.deadline) < utc_time:
                            remove_list.append(user)
                    if (len(users_left) - len(remove_list) == 0) and (len(remove_list) > 0):
                        winner: VigilUser = VigilUser(0, datetime(1070, 1, 1), is_dummy=True)  # Dummy user
                        for user in remove_list:
                            if user.active_time[len(user.active_time) - 1] >\
                                    winner.active_time[len(winner.active_time) - 1]:
                                winner = user
                        self.update_winner(day_string, timezone, VigilWinner(winner))
                    for user in remove_list:
                        del self.hall[user.id]
                if localized_time.hour > 6:
                    self.apply_auto_join(timezone)


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
            localtime: datetime = pytz.utc.localize(datetime.utcnow(), is_dst=None).astimezone(timezone)
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

    def hall_status(self, group) -> str or None:
        content: str = ''
        for timezone in pytz.all_timezones:
            users: list = group.find_user_with_timezone(group.hall, timezone)
            if len(users) > 0:
                content += self.strings.STATUS_BROADCAST.format(timezone=timezone, number=len(users)) + '\n'
        if content != '':
            return content
        else:
            return None

    async def broadcast_winner(self):
        now = datetime.utcnow()
        date: str = now.strftime('%Y/%m/%d')
        for group in self.data['groups'].values():
            group.find_winner()
            self.update_group(group)
            if date not in group.winners.keys():
                continue
            result: str = ''
            for timezone in group.winners[date].keys():
                winner: VigilWinner = group.winners[date][timezone]
                if (not winner) or winner.broadcasted:
                    continue
                user: types.ChatMember = await self.bot.get_chat_member(group.id, winner.id)
                user_name: str = user.user.first_name
                user_name += ' ' + user.user.last_name if user.user.last_name else ''
                result += self.strings.WINNER_FOUND.format(
                    timezone=timezone,
                    user='[%s](tg://user?id=%s)' % (user_name, user.user.id)
                ) + '\n'
                winner.broadcasted = True
                group.update_winner(date, timezone, winner)
            self.update_group(group)
            if result:
                await self.bot.send_message(group.id, result, parse_mode='Markdown')

    async def broadcast_status(self):
        for group in self.data['groups'].values():
            if not group.broadcast_status:
                continue
            content = self.hall_status(group)
            if content:
                await self.bot.send_message(group.id, content)

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
            mode: str = ''
            unit: str = ''
            if group.mode.mode == VigilMode.LAST:
                mode = '截至时间之前最后一个发言的赢'
                unit = ' 点（24 小时制）'
            elif group.mode.mode == VigilMode.NO_ACTIVITY:
                mode = '指定时间内不发言就自动退赛，最后一人赢'
                unit = ' 分'
            response: str = self.strings.GROUP_STATUS.format(
                id=str(group.id),
                enabled='是' if group.enabled else '否',
                timezone=str(group.timezone),
                title_enabled='是' if group.title_enabled else '否',
                title_template=str(group.title_template),
                broadcast_enabled='是' if group.broadcast_status else '否',
                mode=mode,
                deadline=str(group.deadline) + unit
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

    async def handler_match_status(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and group.enabled:
            response = self.hall_status(group)
            if response:
                await message.reply(response)
            else:
                await message.reply(self.strings.STATUS_EMPTY)

    async def handler_update_mode(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            try:
                mode_string: str = str(message.text.split(' ', maxsplit=1)[1]).lower()
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            if mode_string == 'last':
                group.mode = VigilMode(VigilMode.LAST)
            elif mode_string == 'no_activity':
                group.mode = VigilMode(VigilMode.NO_ACTIVITY)
            else:
                await message.reply(self.strings.MODE_INVALID)
                return
            self.update_group(group)
            logger.info('Mode updated to "%s" for group with ID "%s"' % (mode_string, group.id))
            await message.reply(self.strings.MODE_UPDATED.format(mode=mode_string))

    async def handler_update_deadline(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            try:
                time: int = int(message.text.split(' ', maxsplit=1)[1])
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            except ValueError:
                await message.reply(self.strings.DEADLINE_INVALID)
                return
            group.deadline = time
            self.update_group(group)
            logger.info('Deadline of group "%s" has been updated to "%s"' % (group.id, time))
            await message.reply(self.strings.DEADLINE_UPDATED.format(deadline=time))

    async def handler_enable_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if not group.broadcast_status:
                group.broadcast_status = True
                self.update_group(group)
                logger.info('Broadcasting enabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_ENABLED)

    async def handler_disable_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)):
            if group.broadcast_status:
                group.broadcast_status = False
                self.update_group(group)
                logger.info('Broadcasting disabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_DISABLED)

    async def handler_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            try:
                timezone = message.text.split(' ', maxsplit=1)[1]
            except IndexError:
                timezone = group.timezone
            if timezone not in pytz.all_timezones:
                await message.reply(self.strings.TIMEZONE_INVALID)
                return
            user = VigilUser(message.from_user.id, datetime.utcnow(), timezone=timezone)
            group.update_hall(user)
            self.update_group(group)
            logger.info('User with ID "%s" joined the contest in group "%s"' % (user.id, group.id))
            await message.reply(self.strings.JOINED.format(timezone=timezone))

    async def handler_quit(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            user: VigilUser or None = group.get_user(message.from_user.id)
            if user:
                del group.hall[message.from_user.id]
                logger.info('User with ID "%s" quit' % user.id)
                self.update_group(group)
            await message.reply(self.strings.QUIT)

    async def handler_auto_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            user = group.get_user(message.from_user.id)
            if not user:
                await self.handler_join(message)
                group: VigilGroup = self.get_group(message.chat.id)
                user = group.get_user(message.from_user.id)
            user.active_time: list = list()
            user.active_time.append(datetime.utcnow())
            group.auto_join[user.id]: VigilUser = user
            logger.info('User "%s" enabled auto join' % message.from_user.id)
            self.update_group(group)
            await message.reply(self.strings.AUTO_JOIN_ENABLED.format(timezone=user.timezone))

    async def handler_disable_auto_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            user: VigilUser or None = group.auto_join.get(message.from_user.id, None)
            if user:
                del group.auto_join[user.id]
                logger.info('User "%s" disabled auto join' % message.from_user.id)
                self.update_group(group)
            await message.reply(self.strings.AUTO_JOIN_DISABLED)

    async def handler_update_user(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if not group:
            return
        user: VigilUser or None = group.get_user(message.from_user.id)
        if not user:
            return
        user.active_time.append(datetime.utcnow())
        group.update_hall(user)
        self.update_group(group)
        logger.info('Status of user "%s" in group "%s" updated' % (user.id, group.id))

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
            (['current_title_template'], self.handler_current_title_template),
            (['update_mode'], self.handler_update_mode),
            (['update_deadline'], self.handler_update_deadline),
            (['enable_broadcast'], self.handler_enable_broadcast),
            (['disable_broadcast'], self.handler_disable_broadcast),
            (['status', 'match_status'], self.handler_match_status),
            (['join'], self.handler_join),
            (['quit'], self.handler_quit),
            (['auto_join'], self.handler_auto_join),
            (['disable_auto_join'], self.handler_disable_auto_join)
        ]
        for command in commands:
            self.dispatcher.register_message_handler(command[1], commands=command[0])
            logger.info('Command "%s" registered' % command[0])
        self.dispatcher.register_message_handler(self.handler_update_user)
        self.scheduler.add_job(self.update_title_all, 'interval', hours=1, next_run_time=datetime.now())
        self.scheduler.add_job(self.broadcast_winner, 'cron', minute='*/1', next_run_time=datetime.now())
        self.scheduler.add_job(self.broadcast_status, 'cron', hour='*/2')
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