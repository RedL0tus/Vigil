#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os
import pytz
import yaml
import logging

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types.message import ContentType
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
    是否启用状态广播： {broadcast_status_enabled}
    是否启用冠军广播： {broadcast_winner_enabled}
    裁判模式： {mode}
    指定时间： {deadline}
    开赛时间： {start_time} 点整
    结束时间： {stop_time} 点整
    是否延迟公布冠军到结束时间： {winner_broadcast_delay_enabled}
    '''  # 格式化歪打正着
    GROUP_STATUS_SLAVE: str = '''\
    群组 ID： {id}
    主群组 ID： {master_id}
    时区： {timezone}
    是否启用标题自动更新： {title_enabled}
    标题模板： "{title_template}"
    '''
    STATUS_BROADCAST: str = '处于 {offset} offset 的 {timezone} 赛区还有 {number} 人参赛'
    STATUS_EMPTY: str = '无人参赛，你们太弱了'
    MATCH_START_BROADCAST: str = '处于 {offset} offset 的 {timezone} 赛区的守夜大赛正式开始！共有 {number} 人参赛，祝各位武运昌隆（flag）！'
    MATCH_GOING_TO_START_BROADCAST: str = '处于 {offset} offset 的 {timezone} 赛区的大赛将在一小时后开始，请各位选手做好准备！还未参赛的选手请速速报名！'
    BROADCAST_ENABLED: str = '已启用广播'
    BROADCAST_DISABLED: str = '已禁用广播'
    WINNER_BROADCAST_DELAY_ENABLED: str = '冠军将于设定时间公布'
    WINNER_BROADCAST_DELAY_DISABLED: str = '冠军将于决出时公布'
    TIMEZONE_CURRENT: str = '当前时区为 {timezone}'
    TIMEZONE_INVALID: str = '无效的赛区'
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
    TIME_UPDATED: str = '已更新至 {time}'
    TIME_INVALID: str = '无效的时间，必须是个整数'
    JOINED: str = '已加入 {timezone} 场次'
    MATCH_STARTED: str = '{timezone} 场次的比赛已经开始，请不要中途加入'
    QUIT: str = '已退出本届大赛'
    AUTO_JOIN_ENABLED: str = '已设置自动加入 {timezone} 场次'
    AUTO_JOIN_DISABLED: str = '已取消自动加入'
    WINNER_FOUND: str = '本届大赛 {offset} offset 的赛区（{timezone}）的冠军是 {user} ，于当地时间 {time} 决出'
    INVALID_STRING: str = '草这什么鬼名字'
    TIME_RESPONSE: str = '{timezone} 赛区的时间为 {time}'
    I_AM_AWAKE_RESPONSE: str = '我活了'
    LIST_MEMBER: str = '"{name}"，属于 {timezone} 赛区'
    MY_STATUS_MEMBER: str = '你在 {group_name} 群参加了 {timezone} 赛区的大赛'


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

    def __init__(self, user: VigilUser, timezones: list, broadcasted: bool = False):
        self.id: int = user.id
        self.last_online: datetime = user.active_time[len(user.active_time) - 1]
        self.timezones: list = timezones
        self.broadcasted: bool = broadcasted


class VigilChatMember(object):
    def __init__(self, user: types.User):
        self.id: int = user.id
        self.name: str = user.full_name
        self.username: str or None = user.username
        self.record_time: datetime = datetime.utcnow()


class VigilGroup(yaml.YAMLObject):
    yaml_loader: yaml.SafeLoader = yaml.SafeLoader
    yaml_dumper: yaml.SafeDumper = yaml.SafeDumper
    yaml_tag: str = '!VigilGroup'

    def __init__(
            self, group_id: int,
            enabled: bool = False,
            master: bool = True,
            slave_of: int = 0,
            timezone: str = 'Asia/Shanghai',
            title_enabled: bool = False,
            title_template: str = '椰树 {yeshu_year} 年第 {day} 届守夜大赛',
            mode: VigilMode = VigilMode(VigilMode.LAST),
            deadline: int = 6,
            start_time: int = 0,
            stop_time: int = 9,
            delay_winner_broadcast: bool = False,
            broadcast_status: bool = False,
            broadcast_winner: bool = True
    ):
        self.id: int = group_id
        self.enabled: bool = enabled
        self.master: bool = master
        self.slave_of: int = slave_of
        self.timezone: str = timezone
        self.title_enabled: bool = title_enabled
        self.title_template: str = title_template
        self.auto_join: dict = dict()
        self.hall: dict = dict()
        self.mode: VigilMode = mode
        self.deadline: int = deadline
        self.start_time: int = start_time
        self.stop_time: int = stop_time
        self.delay_winner_broadcast: bool = delay_winner_broadcast
        self.winners: dict = dict()
        self.broadcast_status: bool = broadcast_status
        self.broadcast_winner: bool = broadcast_winner

    def check_integrity(self):
        default_values = {  # Default values
            'enabled': False,
            'master': True,
            'slave_of': '0',
            'timezone': 'Asia/Shanghai',
            'title_enabled': False,
            'title_template': '椰树 {yeshu_year} 年第 {day} 届守夜大赛',
            'auto_join': dict(),
            'hall': dict(),
            'mode': VigilMode(VigilMode.LAST),
            'deadline': 6,
            'start_time': 0,
            'stop_time': 9,
            'delay_winner_broadcast': False,
            'winners': dict(),
            'broadcast_status': False,
            'broadcast_winner': True
        }
        if 'id' not in self.__dict__.keys():
            raise ValueError('Corrupted group data: WTF is this group?')  # Manual correction needed
        for key in default_values.keys():
            if key not in self.__dict__.keys():
                logger.warning('Key "%s" not found for group "%s", applying default value' % (key, self.id))
                self.__dict__[key] = default_values[key]

    def get_user(self, user_id) -> VigilUser or None:
        return self.hall.get(user_id, None)

    def update_hall(self, user: VigilUser):
        logger.info('Information of user with ID "%s" updated' % user.id)
        self.hall[user.id] = user

    def update_winner(self, date: str, offset: str, winner: VigilWinner):
        logger.info('Information of winner with ID "%s" updated' % winner.id)
        if not self.winners.get(date, None):
            self.winners[date]: dict = dict()
        self.winners[date][offset] = winner

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

    def apply_auto_join(self):
        utc_now: datetime = datetime.utcnow()
        for timezone in pytz.all_timezones:
            user_list: list = self.find_user_with_timezone(self.auto_join, timezone)
            if len(user_list) < 1:
                continue
            localized_time: datetime = pytz.utc.localize(utc_now, is_dst=None).astimezone(pytz.timezone(timezone))
            if self.mode.mode == VigilMode.LAST:
                if localized_time.hour != self.deadline:
                    continue
                elif localized_time.minute != 30:
                    continue
            if self.mode.mode == VigilMode.NO_ACTIVITY:
                if localized_time.hour != self.stop_time:
                    continue
                elif localized_time.minute not in range(1):
                    continue
            for user in user_list:
                user.active_time = list()
                user.active_time.append(datetime.utcnow())
                if user.id not in self.hall.keys():
                    self.hall[user.id] = user

    def i_dont_know_how_to_name_this_method(self) -> dict:
        result: dict = dict()
        utc_now: datetime = datetime.utcnow()
        for timezone in pytz.all_timezones:
            user_list: list = self.find_user_with_timezone(self.hall, timezone)
            if len(user_list) < 1:
                continue
            tz: pytz.timezone = pytz.timezone(timezone)
            offset = pytz.utc.localize(utc_now, is_dst=None).astimezone(tz).strftime('%z')
            if offset not in result.keys():
                result[offset] = (list(), list())
            (timezones, users) = result[offset]
            timezones.append(timezone)
            users = users + user_list
            result[offset] = (timezones, users)
        return result

    @staticmethod
    def find_latest_user(users) -> VigilUser or None:
        if len(users) == 0:
            return None
        last_user: VigilUser = VigilUser(0, datetime(1970, 1, 1), is_dummy=True)  # Dummy user
        for user in users:
            if user.active_time[len(user.active_time) - 1] > \
                    last_user.active_time[len(last_user.active_time) - 1]:
                last_user = user
        return last_user

    def find_winner(self):
        if (not self.enabled) or (not self.master):
            return
        utc_time: datetime = datetime.utcnow()
        day_string: str = utc_time.strftime('%Y/%m/%d')
        users_in_matches: dict = self.i_dont_know_how_to_name_this_method()
        for offset, (timezones, users) in users_in_matches.items():
            tz: pytz.timezone = pytz.timezone(timezones[0])
            localized_time: datetime = pytz.utc.localize(utc_time, is_dst=None).astimezone(tz)
            if localized_time.hour > ((self.stop_time + 1) % 24):
                continue
            elif (localized_time.hour >= self.start_time) and (localized_time.hour < self.stop_time):
                if len(users) == 1:
                    self.update_winner(day_string, offset, VigilWinner(users[0], timezones))
                    del self.hall[users[0].id]
            if self.mode.mode == VigilMode.LAST:
                if self.deadline not in range(24):
                    continue
                if len(users) == 0:
                    continue
                if (localized_time.hour == self.deadline) and (localized_time.minute == 0):
                    winner: VigilUser = self.find_latest_user(users)
                    self.update_winner(day_string, offset, VigilWinner(winner, timezones))
                    for timezone in timezones:
                        self.clean_up_hall(timezone)
            if self.mode.mode == VigilMode.NO_ACTIVITY:
                if (localized_time.hour >= ((self.start_time + 1) % 24)) and (localized_time.hour < self.stop_time):
                    remove_list: list = list()
                    for user in users:
                        if user.active_time[len(user.active_time) - 1] + timedelta(minutes=self.deadline) < utc_time:
                            remove_list.append(user)
                    if (len(users) - len(remove_list) == 0) and (len(remove_list) > 0):
                        winner: VigilUser or None = self.find_latest_user(remove_list)
                        if winner:
                            self.update_winner(day_string, offset, VigilWinner(winner, timezones))
                    for user in remove_list:
                        try:
                            del self.hall[user.id]
                        except KeyError:
                            continue
        self.apply_auto_join()


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
        for group in self.data['groups'].values():
            logger.info('Inspecting group with ID "%s"' % group.id)
            group.check_integrity()
            self.data['groups'][group.id] = group
        if 'admins' not in self.data.keys():
            self.data['admins']: list = list()
        self.data['admins']: list = list(set(self.data['admins'] + admins))
        self.dump_data()
        self.chat_members: dict = dict()

    def html_escape_for_the_damn_parser_of_telegram(self, text):
        try:
            return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        except AttributeError:
            return self.strings.INVALID_STRING

    def load_data(self):
        if os.path.isfile(self.data_path):
            with open(self.data_path) as f:
                self.data = yaml.safe_load(f)
                logger.info('Data loaded from "%s"' % self.data_path)

    def dump_data(self):
        with open(self.data_path, 'w+') as f:
            yaml.safe_dump(self.data, f)
            logger.info('Data dumped to "%s"' % self.data_path)

    def add_group(self, group_id: int, master: bool = True, slave_of: int = 0):
        if group_id >= 0:
            logger.info('Invalid group ID')
            return
        if group_id not in self.data['groups'].keys():
            self.data['groups'][group_id]: VigilGroup = VigilGroup(group_id, master=master, slave_of=slave_of)
            logger.info('Group with ID "%s" has been added' % group_id)
            self.dump_data()

    def get_group(self, group_id: int, follow_redir: bool = False) -> VigilGroup or None:
        group: VigilGroup or None = self.data['groups'].get(group_id, None)
        if not group:
            return None
        if follow_redir and (not group.master):
            return self.data['groups'].get(group.slave_of, None)
        else:
            return group

    def update_group(self, group: VigilGroup):
        if group.id in self.data['groups'].keys():
            self.data['groups'][group.id] = group
            logger.info('Group with ID "%s" has been updated' % group.id)
            self.dump_data()

    def hall_status(self, group) -> str or None:
        content: str = ''
        for offset, (timezones, users) in group.i_dont_know_how_to_name_this_method().items():
            if len(users) > 0:
                content += self.strings.STATUS_BROADCAST.format(
                    offset=offset,
                    timezone=', '.join(timezones),
                    number=len(users)
                ) + '\n'
        if content != '':
            return content
        else:
            return None

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

    async def get_member_name(self, user_id: int, group_id: int) -> VigilChatMember:
        if user_id not in self.chat_members.keys() or\
                (self.chat_members[user_id].record_time + timedelta(hours=12) < datetime.utcnow()):
            logger.info('No valid user information cache found for user "%s", fetching...' % user_id)
            chat_member: types.ChatMember = await self.bot.get_chat_member(group_id, user_id)
            self.chat_members[user_id]: VigilChatMember = VigilChatMember(chat_member.user)
        return self.chat_members[user_id]

    async def broadcast_winner(self):
        now = datetime.utcnow()
        date: str = now.strftime('%Y/%m/%d')
        for group in self.data['groups'].values():
            if not group.master:
                continue
            group.find_winner()
            self.update_group(group)
            if date not in group.winners.keys():
                continue
            result: str = ''
            for offset, winner in group.winners[date].items():
                if (not winner) or winner.broadcasted:
                    continue
                tz: pytz.timezone = pytz.timezone(winner.timezones[0])
                localized_time: datetime = pytz.utc.localize(winner.last_online, is_dst=None).astimezone(tz)
                time_string: str = localized_time.strftime('%H:%M')
                if group.delay_winner_broadcast and (localized_time.hour != group.stop_time):
                    continue
                user: VigilChatMember = await self.get_member_name(winner.id, group.id)
                user_name: str = self.html_escape_for_the_damn_parser_of_telegram(user.name)
                result += self.strings.WINNER_FOUND.format(
                    offset=offset,
                    timezone=self.html_escape_for_the_damn_parser_of_telegram(', '.join(winner.timezones)),
                    user='<a href="tg://user?id=%s">%s</a>' % (user.id, user_name),
                    time=time_string
                ) + '\n'
                winner.broadcasted = True
                group.update_winner(date, offset, winner)
            self.update_group(group)
            if result and group.broadcast_winner:
                await self.bot.send_message(group.id, result, parse_mode='HTML')

    async def broadcast_match_start(self):
        now = datetime.utcnow()
        for group in self.data['groups'].values():
            if (not group.broadcast_status) or (not group.master):
                continue
            for offset, (timezones, users) in group.i_dont_know_how_to_name_this_method().items():
                if len(users) > 0:
                    tz: pytz.timezone = pytz.timezone(timezones[0])
                    localized_time: datetime = pytz.utc.localize(now, is_dst=None).astimezone(tz)
                    prepare_time: int = (24 + group.start_time - 1) % 24
                    if (localized_time.hour == group.start_time) and (localized_time.minute == 0):
                        await self.bot.send_message(
                            group.id,
                            self.strings.MATCH_START_BROADCAST.format(
                                offset=offset,
                                timezone=', '.join(timezones),
                                number=len(users)
                            )
                        )
                    elif (localized_time.hour == prepare_time) and (localized_time.minute == 0):
                        await self.bot.send_message(
                            group.id,
                            self.strings.MATCH_GOING_TO_START_BROADCAST.format(
                                offset=offset,
                                timezone=', '.join(timezones)
                            )
                        )

    async def broadcast_hall_status(self):
        for group in self.data['groups'].values():
            if (not group.broadcast_status) or (not group.master):
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

    async def handler_slave(self, message: types.Message):
        if message.from_user.id not in self.data['admins']:
            return
        try:
            master: int = int(message.text.split(' ', maxsplit=1)[1])
        except IndexError:
            await message.reply(self.strings.TOO_LESS_ARGUMENTS)
            return
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group:
            del self.data['groups'][group.id]
        self.add_group(message.chat.id, master=False, slave_of=master)
        await message.reply(self.strings.GROUP_ADDED.format(id=master))  # Because I'm too lazy to write another string.

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
        if group and (await self.is_valid(group, message)):
            if not group.master:
                await message.reply(
                    self.strings.GROUP_STATUS_SLAVE.format(
                        id=str(group.id),
                        master_id=str(group.slave_of),
                        timezone=str(group.timezone),
                        title_enabled='是' if group.enabled else '否',
                        title_template=str(group.title_template)
                    )
                )
                return
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
                broadcast_status_enabled='是' if group.broadcast_status else '否',
                broadcast_winner_enabled='是' if group.broadcast_winner else '否',
                mode=mode,
                deadline=str(group.deadline) + unit,
                start_time=str(group.start_time),
                stop_time=str(group.stop_time),
                winner_broadcast_delay_enabled='是' if group.delay_winner_broadcast else '否',
            )
            await message.reply(response)

    async def handler_current_timezone(self, message: types.Message):
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
        if group and group.enabled and group.master:
            response = self.hall_status(group)
            if response:
                await message.reply(response)
            else:
                await message.reply(self.strings.STATUS_EMPTY)

    async def handler_update_mode(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
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

    async def handler_update_start_time(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            try:
                start_time: int = int(message.text.split(' ', maxsplit=1)[1])
                if start_time not in range(24):
                    raise ValueError
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            except ValueError:
                await message.reply(self.strings.TIME_INVALID)
                return
            group.start_time = start_time
            self.update_group(group)
            logger.info('Start time of group "%s" has been updated to "%s"' % (group.id, start_time))
            await message.reply(self.strings.TIME_UPDATED.format(time=start_time))

    async def handler_update_stop_time(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            try:
                stop_time: int = int(message.text.split(' ', maxsplit=1)[1])
                if stop_time not in range(24):
                    raise ValueError
            except IndexError:
                await message.reply(self.strings.TOO_LESS_ARGUMENTS)
                return
            except ValueError:
                await message.reply(self.strings.TIME_INVALID)
                return
            group.stop_time = stop_time
            self.update_group(group)
            logger.info('Start time of group "%s" has been updated to "%s"' % (group.id, stop_time))
            await message.reply(self.strings.TIME_UPDATED.format(time=stop_time))

    async def handler_enable_winner_broadcast_delay(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if not group.delay_winner_broadcast:
                group.delay_winner_broadcast = True
                self.update_group(group)
                logger.info('Broadcast delay enabled for group "%s"' % group.id)
            await message.reply(self.strings.WINNER_BROADCAST_DELAY_ENABLED)

    async def handler_disable_winner_broadcast_delay(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if group.delay_winner_broadcast:
                group.delay_winner_broadcast = False
                self.update_group(group)
                logger.info('Broadcast delay disabled for group "%s"' % group.id)
            await message.reply(self.strings.WINNER_BROADCAST_DELAY_DISABLED)

    async def handler_update_deadline(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
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

    async def handler_enable_status_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if not group.broadcast_status:
                group.broadcast_status = True
                self.update_group(group)
                logger.info('Broadcasting enabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_ENABLED)

    async def handler_disable_status_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if group.broadcast_status:
                group.broadcast_status = False
                self.update_group(group)
                logger.info('Broadcasting disabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_DISABLED)

    async def handler_enable_winner_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if not group.broadcast_winner:
                group.broadcast_winner = True
                self.update_group(group)
                logger.info('Broadcasting enabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_ENABLED)

    async def handler_disable_winner_broadcast(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and (await self.is_valid(group, message)) and group.master:
            if group.broadcast_winner:
                group.broadcast_winner = False
                self.update_group(group)
                logger.info('Broadcasting disabled for group with ID "%s"' % group.id)
            await message.reply(self.strings.BROADCAST_DISABLED)

    async def handler_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and group.enabled and group.master:
            try:
                timezone = message.text.split(' ', maxsplit=1)[1]
            except IndexError:
                timezone = group.timezone
            if timezone not in pytz.all_timezones:
                await message.reply(self.strings.TIMEZONE_INVALID)
                return
            tz: pytz.timezone = pytz.timezone(timezone)
            localized_time: datetime = pytz.utc.localize(datetime.utcnow(), is_dst=None).astimezone(tz)
            if (localized_time.hour < group.stop_time) or (localized_time.hour >= group.start_time):
                await message.reply(self.strings.MATCH_STARTED.format(timezone=timezone))
                return
            user = VigilUser(message.from_user.id, datetime.utcnow(), timezone=timezone)
            group.update_hall(user)
            self.update_group(group)
            logger.info('User with ID "%s" joined the contest in group "%s"' % (user.id, group.id))
            await message.reply(self.strings.JOINED.format(timezone=timezone))

    async def handler_quit(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and group.enabled and group.master:
            user: VigilUser or None = group.get_user(message.from_user.id)
            if user:
                del group.hall[message.from_user.id]
                logger.info('User with ID "%s" quit' % user.id)
                self.update_group(group)
            await message.reply(self.strings.QUIT)

    async def handler_auto_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and group.enabled and group.master:
            user = group.get_user(message.from_user.id)
            if not user:
                await self.handler_join(message)
                group: VigilGroup = self.get_group(message.chat.id)
                user = group.get_user(message.from_user.id)
            if not user:
                try:
                    timezone = message.text.split(' ', maxsplit=1)[1]
                except IndexError:
                    timezone = group.timezone
                if timezone not in pytz.all_timezones:
                    await message.reply(self.strings.TIMEZONE_INVALID)
                    return
                user: VigilUser = VigilUser(message.from_user.id, datetime.utcnow(), timezone=timezone)
            user.active_time: list = list()
            user.active_time.append(datetime.utcnow())
            group.auto_join[user.id]: VigilUser = user
            logger.info('User "%s" enabled auto join' % message.from_user.id)
            self.update_group(group)
            await message.reply(self.strings.AUTO_JOIN_ENABLED.format(timezone=user.timezone))

    async def handler_disable_auto_join(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if group and group.enabled and group.master:
            user: VigilUser or None = group.auto_join.get(message.from_user.id, None)
            if user:
                del group.auto_join[user.id]
                logger.info('User "%s" disabled auto join' % message.from_user.id)
                self.update_group(group)
            await message.reply(self.strings.AUTO_JOIN_DISABLED)

    async def handler_time(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id, follow_redir=True)
        if (not group) or (not group.enabled):
            return
        user: VigilUser or None = group.get_user(message.from_user.id)
        utc_time: datetime = datetime.utcnow()
        try:
            timezone = str(message.text.split(' ', maxsplit=1)[1])
        except IndexError:
            if user:
                timezone: str = user.timezone
            else:
                user: VigilUser or None = group.auto_join.get(message.from_user.id, None)
                if user:
                    timezone: str = user.timezone
                else:
                    timezone: str = group.timezone
        if timezone not in pytz.all_timezones:
            await message.reply(self.strings.TIMEZONE_INVALID)
            return
        tz: pytz.timezone = pytz.timezone(timezone)
        localized_time: datetime = pytz.utc.localize(utc_time, is_dst=None).astimezone(tz)
        response: str = self.strings.TIME_RESPONSE.format(
            timezone=timezone, time=localized_time.strftime('%H:%M')
        ) + '\n'
        response += self.strings.TIME_RESPONSE.format(timezone='UTC', time=utc_time.strftime('%H:%M'))
        await message.reply(response)

    async def handler_list(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if (not group) or (not group.enabled) or (not group.master):
            return
        try:
            timezone: str = str(message.text.split(' ', maxsplit=1)[1])
            if (len(timezone) != 5) and (timezone not in pytz.all_timezones):
                raise ValueError
        except IndexError:
            timezone: str = ''
        except ValueError:
            await message.reply(self.strings.TIMEZONE_INVALID)
            return
        if not timezone:
            users_list: list = list(group.hall.values())
        elif timezone not in pytz.all_timezones:
            all_users: dict = group.i_dont_know_how_to_name_this_method()
            _, users_list = all_users.get(timezone, (None, None))
        else:
            users_list: list = group.find_user_with_timezone(group.hall, timezone)
        if not users_list:
            response = self.strings.STATUS_EMPTY
        else:
            response: str = ''
            for user in users_list:
                user_info: VigilChatMember = await self.get_member_name(user.id, group.id)
                user_name: str = self.html_escape_for_the_damn_parser_of_telegram(user_info.name)
                response += self.strings.LIST_MEMBER.format(name=user_name, timezone=user.timezone) + '\n'
        if response:
            await message.reply(response)

    async def handler_my_status(self, message: types.Message):
        if message.chat.id != message.from_user.id:
            return
        response: str = ''
        for group in self.data['groups'].values():
            if message.from_user.id not in group.hall.keys():
                continue
            group_info: types.Chat = await self.bot.get_chat(group.id)
            if group_info.username:
                group_name: str = '@%s' % group_info.username
            else:
                group_name: str = '“%s”' % group_info.title
            response += self.strings.MY_STATUS_MEMBER.format(
                group_name=group_name,
                timezone=group.hall[message.from_user.id].timezone
            )
        if response:
            await message.reply(response)

    async def handler_update_user(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id, follow_redir=True)
        if (not group) or (not group.enabled):
            return
        user: VigilUser or None = group.get_user(message.from_user.id)
        if not user:
            return
        self.chat_members[user.id]: VigilChatMember = VigilChatMember(message.from_user)
        tz: pytz.timezone = pytz.timezone(user.timezone)
        localized_time: datetime = pytz.utc.localize(datetime.utcnow(), is_dst=None).astimezone(tz)
        start_time: int = (24 + group.start_time - group.deadline) % 24
        if (localized_time.hour < group.stop_time) or (localized_time.hour >= start_time):
            user.active_time.append(datetime.utcnow())
            group.update_hall(user)
            self.update_group(group)
            logger.info('Status of user "%s" in group "%s" updated' % (user.id, group.id))

    async def handler_imawake(self, message: types.Message):
        await self.handler_update_user(message)
        await message.reply(self.strings.I_AM_AWAKE_RESPONSE)

    async def handler_stop(self, message: types.Message):
        group: VigilGroup or None = self.get_group(message.chat.id)
        if not group:
            return
        if await self.is_valid(group, message):
            del self.data['groups'][group.id]
            logger.info('Information deleted for group with ID "%s"' % group.id)

    def start(self):
        commands = [
            (['add_admin'], self.handler_add_admin),
            (['add_group'], self.handler_add_group),
            (['enable'], self.handler_enable),
            (['slave'], self.handler_slave),
            (['disable'], self.handler_disable),
            (['group_status'], self.handler_group_status),
            (['current_timezone'], self.handler_current_timezone),
            (['update_timezone'], self.handler_update_timezone),
            (['enable_title_update'], self.handler_enable_title_update),
            (['disable_title_update'], self.handler_disable_title_update),
            (['update_title_template'], self.handler_update_title_template),
            (['current_title_template'], self.handler_current_title_template),
            (['update_mode'], self.handler_update_mode),
            (['update_deadline'], self.handler_update_deadline),
            (['update_start_time'], self.handler_update_start_time),
            (['update_stop_time'], self.handler_update_stop_time),
            (['enable_broadcast', 'enable_status_broadcast'], self.handler_enable_status_broadcast),
            (['disable_broadcast', 'disable_status_broadcast'], self.handler_disable_status_broadcast),
            (['enable_winner_broadcast'], self.handler_enable_winner_broadcast),
            (['disable_winner_broadcast'], self.handler_disable_winner_broadcast),
            (['enable_winner_broadcast_delay'], self.handler_enable_winner_broadcast_delay),
            (['disable_winner_broadcast_delay'], self.handler_disable_winner_broadcast_delay),
            (['status', 'match_status'], self.handler_match_status),
            (['join'], self.handler_join),
            (['quit'], self.handler_quit),
            (['auto_join'], self.handler_auto_join),
            (['disable_auto_join'], self.handler_disable_auto_join),
            (['time'], self.handler_time),
            (['imawake'], self.handler_imawake),
            (['stop'], self.handler_stop),
            (['list'], self.handler_list),
            (['my_status'], self.handler_my_status)
        ]
        for command in commands:
            self.dispatcher.register_message_handler(command[1], commands=command[0])
            logger.info('Command "%s" registered' % command[0])
        self.dispatcher.register_message_handler(self.handler_update_user, content_types=ContentType.ANY)
        self.scheduler.add_job(self.update_title_all, 'cron', minute='*/30', next_run_time=datetime.now())
        self.scheduler.add_job(self.broadcast_winner, 'cron', minute='*/1', next_run_time=datetime.now())
        self.scheduler.add_job(self.broadcast_match_start, 'cron', minute='*/30')
        self.scheduler.add_job(self.broadcast_hall_status, 'cron', hour='*/2')
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
