from httpx import HTTPStatusError
from ncatbot.plugin_system import NcatBotPlugin, command_registry, filter_registry, admin_filter, on_group_at
from dataclasses import dataclass, field
from .config_proxy import ProxiedPluginConfig
from ncatbot.utils import get_log
from ncatbot.core.event import GroupMessageEvent, BaseMessageEvent
from ncatbot.core.event.message_segment.message_segment import Reply, Text, PlainText
import httpx
import re

PLUGIN_NAME = 'UnnamedCmIntegrate'

logger = get_log(PLUGIN_NAME)
GROUP_FILTER_NAME = '__unnamed_cm_group_filter__'


@filter_registry.register(GROUP_FILTER_NAME)
def filter_group_by_config(event: BaseMessageEvent) -> bool:
    if not event.is_group_event():
        return False
    assert isinstance(event, GroupMessageEvent)
    if global_plugin_instance is None:
        raise RuntimeError(f"无法获取到插件实例, 你是不是直接引用了这个文件")
    if not global_plugin_instance.cm_config.enable_group_filter:
        return True
    return int(event.group_id) in global_plugin_instance.cm_config.filter_group


@dataclass
class CmConfig(ProxiedPluginConfig):
    auth_token: str = field(default='')
    base_url: str = field(default='')
    enable_group_filter: bool = field(default=False)
    filter_group: list[int] = field(default_factory=list)


def extract_hitomi_id(hitomi_url: str) -> str | None:
    __match = re.search(r'(\d+)\.html$', hitomi_url)
    if __match:
        return __match.group(1)
    return None


class UnnamedCmIntegrate(NcatBotPlugin):
    name = PLUGIN_NAME  # 必须，插件名称，要求全局独立
    version = "0.0.1"  # 必须，插件版本
    dependencies = {}  # 必须，依赖的其他插件和版本
    description = "集成色孽神选"  # 可选
    author = "default_user"  # 可选

    cm_config: CmConfig | None = None
    init = False

    async def on_load(self) -> None:
        self.cm_config = CmConfig(self)
        global global_plugin_instance
        global_plugin_instance = self
        if not self.cm_config.base_url or not self.cm_config.auth_token:
            logger.error(f'未配置后端url或auth token, 神选集成将禁用')
            return
        logger.info(f'测试色孽神选后端连通性')
        link_ok = False
        async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                     cookies={'auth_token': self.cm_config.auth_token}) as client:
            try:
                resp = await client.get('/api/site/download_status')
                resp.raise_for_status()
                link_ok = True
            except Exception as e:
                logger.exception(f'请求失败', exc_info=e)
        if not link_ok:
            logger.error(f'连通性测试失败, 将禁用神选集成')
            return
        self.init = link_ok
        if self.init:
            await super().on_load()
        else:
            await super().on_close()

    @admin_filter
    @filter_registry.filters(GROUP_FILTER_NAME)
    @on_group_at
    async def at_dispatch(self, event: GroupMessageEvent):
        logger.debug('收到at消息, 开始验证')
        if len(event.message) != 3:
            logger.debug(f'at消息长度不为3, 已取消')
            return
        origin_text = None
        cmd_trigger = False
        for message_segment in event.message:
            if message_segment.msg_seg_type == 'reply':
                assert isinstance(message_segment, Reply)
                reply_ptr = message_segment.id
                origin_msg = await self.api.get_msg(reply_ptr)
                if len(origin_msg.message) > 1:
                    logger.debug(f'引用消息长度超1, 退出')
                    return
                origin_text_msg = origin_msg.message.messages[0]
                if origin_text_msg.msg_seg_type != 'text':
                    logger.debug(f'引用消息类型非纯文字')
                    return
                assert isinstance(origin_text_msg, Text) or isinstance(origin_text_msg, PlainText)
                origin_text = origin_text_msg.text
                # 源自 HayaseYuuka.UnnamedCmIntegrate.HitomiComicSearchResult 取sha256
                if not origin_text.startswith('26a85b4651da987106c8bc0f4aa91de966104ae5ed14be4000132ac26002b74e'):
                    logger.debug(f'开头魔数不匹配, 退出')
                    return
            if message_segment.msg_seg_type == 'text':
                assert isinstance(message_segment, Text) or isinstance(message_segment, PlainText)
                if message_segment.text.replace(' ', '') == 's':
                    cmd_trigger = True

        if not cmd_trigger:
            logger.debug(f'没有触发命令')
            return
        if not origin_text:
            logger.debug(f'没有提取文本')
            return
        search_result = origin_text.splitlines()
        hitomi_id = int(search_result[1])
        try:
            await event.reply(await self.add_comic(hitomi_id))
        except HTTPStatusError as cm_e:
            logger.exception(f'请求过程发生HTTP异常', exc_info=cm_e)
            await event.reply(f'请求过程发生HTTP异常: {str(cm_e)}')
        except Exception as cm_e:
            logger.exception(f'请求过程发生异常', exc_info=cm_e)
            await event.reply(f'请求过程发生异常: {str(cm_e)}')

    async def add_comic(self, hitomi_id: int, func_client: httpx.AsyncClient | None = None):
        async def request(client: httpx.AsyncClient):
            resp = await client.get(f'/api/documents/hitomi/get/{hitomi_id}')
            if resp.status_code == 200:
                comic_info: dict = resp.json()
                document_id = comic_info['document_info']['document_id']
                return f'本子已存在, 访问以下网址\n{self.cm_config.base_url}/show_document/{document_id}'
            if resp.status_code != 404:
                resp.raise_for_status()
            resp = await client.get(f'/api/tags/hitomi/missing_tags?source_document_id={hitomi_id}')
            missing_tags = resp.json()
            if missing_tags:
                redirect_url = f'/hitomi/add?source_document_id={hitomi_id}'
                return f'存在需手动录入的tag, 请前往网页进行添加\n{redirect_url}'
            resp = await client.post('/api/documents/hitomi/add', json={'source_document_id': str(hitomi_id),
                                                                        'inexistent_tags': {}})
            if resp.status_code != 200:
                resp.raise_for_status()
            redirect_url = f'{self.cm_config.base_url}/show_status'
            return f'tag已完备, 已提交录入任务, 访问网页以查看进度\n{redirect_url}'

        if func_client is None:
            async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                         cookies={'auth_token': self.cm_config.auth_token}) as func_client:
                return await request(func_client)
        return await request(func_client)

    async def get_comic_urls(self, hitomi_id: int, func_client: httpx.AsyncClient | None = None):
        async def request(client: httpx.AsyncClient):
            resp = await client.get(f'/api/site/hitomi/download_urls?hitomi_id={hitomi_id}')
            if resp.status_code != 200:
                err_json = resp.json()
                err_detail = err_json.get('detail', None)
                if err_detail:
                    raise RuntimeError(f'错误码 {resp.status_code} 错误详情: {err_detail}')
                resp.raise_for_status()
            return resp.json()

        if func_client is None:
            async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                         cookies={'auth_token': self.cm_config.auth_token}) as func_client:
                return await request(func_client)
        return await request(func_client)

    async def search_comic(self, search_str: str, func_client: httpx.AsyncClient | None = None) -> list[dict]:
        async def request(client: httpx.AsyncClient):
            resp = await client.get(f'/api/documents/hitomi/search?search_str={search_str}')
            if resp.status_code != 200:
                err_json = resp.json()
                err_detail = err_json.get('detail', None)
                if err_detail:
                    raise RuntimeError(f'错误码 {resp.status_code} 错误详情: {err_detail}')
                resp.raise_for_status()
            return resp.json()

        if func_client is None:
            async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                         cookies={'auth_token': self.cm_config.auth_token}) as func_client:
                return await request(func_client)
        return await request(func_client)

    @admin_filter
    @filter_registry.filters(GROUP_FILTER_NAME)
    @command_registry.command('cm')
    async def cm_cmd(self, event: GroupMessageEvent, hitomi_input: str):
        if not self.init:
            await event.reply(f'神选集成未激活, 具体原因看log')
            return
        try:
            hitomi_id = int(hitomi_input)
        except ValueError:
            hitomi_id = extract_hitomi_id(hitomi_input)
        try:
            async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                         cookies={'auth_token': self.cm_config.auth_token}) as client:
                if hitomi_id:
                    await event.reply(await self.add_comic(hitomi_id, client))
                    return
                comic_infos = await self.search_comic(hitomi_input, client)
                for comic_info in comic_infos:
                    # 源自 HayaseYuuka.UnnamedCmIntegrate.HitomiComicSearcgResult 取sha256
                    await self.api.send_group_text(event.group_id,
                                                   f'26a85b4651da987106c8bc0f4aa91de966104ae5ed14be4000132ac26002b74e\n{comic_info["id"]}\n{comic_info["title"]}')
                await event.reply('搜索结果结束')
        except HTTPStatusError as cm_e:
            logger.exception(f'请求过程发生HTTP异常', exc_info=cm_e)
            await event.reply(f'请求过程发生HTTP异常: {str(cm_e)}')
        except Exception as cm_e:
            logger.exception(f'请求过程发生异常', exc_info=cm_e)
            await event.reply(f'请求过程发生异常: {str(cm_e)}')

    async def on_close(self) -> None:
        await super().on_close()


global_plugin_instance: UnnamedCmIntegrate | None = None
